import os
import pdb
import datetime
import torch
import pandas as pd
import numpy as np
import argparse
import pickle
import utils.io.image as io_func
from utils.sitk_np import np_to_sitk
from torchvision.utils import save_image
from shutil import copyfile
from dataloader.MM_loader_4_test_EXTERNAL import MM_loader
from networks.net_cmr_mtdt import net_cmr_mtdt
from mcvae import pytorch_modules, utilities
from utils.trainer_regressor import save_output
from sklearn.preprocessing import RobustScaler


def MI_prediciton(image_names, args):

    # Reading LVM and LVEDV predictions
    lvm_lvedv_preds = pd.read_csv(args.dir_results + 'ids_metadata_EXTERNAL_preds.csv')
    # Reading metadata
    mtdt_test_set = pd.read_csv(args.dir_ids)
    # Sorting by ID
    lvm_lvedv_preds = lvm_lvedv_preds.sort_values(by=['ID'])
    mtdt_test_set = mtdt_test_set.sort_values(by=['ID'])
    # Removing image extension from ID column
    # mtdt_test_set['ID'] = mtdt_test_set.ID.apply(lambda x: x.split('.')[0])
    # Concatenating predictions and metadata
    test_set = pd.concat([lvm_lvedv_preds[['LVEDV', 'LVM']], mtdt_test_set[['sex', 'dbpa', 'sbpa', 'ss', 'ads', 'bmi', 'age']]], axis=1)
    # Rescaling inputs
    scaler = RobustScaler()
    test_set = scaler.fit_transform(test_set)
    # Loading pretrained model
    model_name = args.dir_weights_mcvae + 'best_linear_model.sav'
    # load the model from disk
    loaded_model = pickle.load(open(model_name, 'rb'))
    predicted_y = loaded_model.predict(test_set)
    print('MI predictions: ', predicted_y)
    print('Number of predictions: ', len(predicted_y))
    # Saving the MI predictions
    print('\n -- Saving the MI predictions in results_test folder')
    result = {}
    result['ID'] = image_names
    result['MI_pred'] = [int(p) for p in predicted_y]
    out_df = pd.DataFrame(result)
    out_df.to_csv('./results_test/MI_preds.csv', index=False)
    ## Evaluating model on EXTERNAL dataset
    # result = loaded_model.score(test_set, test_set_labels)
    # print('Evaluation result: ', result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Test mcVAE/Deep Regressor/Logistic for MI')
    parser.add_argument('--n_channels', default=2, type=int) #  number of channels for MCVAE
    parser.add_argument('--lat_dim', default=2048, type=int)
    parser.add_argument('--lr', type=float, default=5e-4)
    parser.add_argument('--epochs', default=2000, type=int)
    parser.add_argument('--save_model', default=200, type=int) # save the model every x epochs
    parser.add_argument('--batch_size', default=8, type=int)
    parser.add_argument('--n_cpu', default=24, type=int)
    parser.add_argument('--dir_dataset', type=str, default='./input_data_EXTERNAL/')
    parser.add_argument('--dir_ids', type=str, default='./input_data_EXTERNAL/ids/ids_metadata_EXTERNAL.csv')
    parser.add_argument('--sax_img_size', type=list, default=[128, 128, 15])
    parser.add_argument('--fundus_img_size', type=int, default=128)
    parser.add_argument('--num_mtdt', type=int, default=7) # ['sex', 'dbpa', 'sbpa', 'ss', 'ads', 'bmi', 'age']
    parser.add_argument('--n_classes', type=int, default=2) # CMR and Fundus
    parser.add_argument('--ndf', type=int, default=128)
    parser.add_argument('--dir_results', type=str, default='./results_test/')
    parser.add_argument('--dir_weights_mcvae', type=str, default='./results/2020-05-13_17-42-01_automatic_1800Epochs_reducedList/')
    parser.add_argument('--dir_weights_regressor', type=str, default='results_regressor/2021-04-06_19-36-20_for_EXTERNAL/')
    parser.add_argument('--model_name', type=str, default='net_cmr_mtdt')  # for deep regressor
    args = parser.parse_args()

    args.dir_weights_regressor = args.dir_weights_mcvae + args.dir_weights_regressor


    # Multi-channel VAE config
    init_dict = {
        'n_channels': args.n_channels,
        'lat_dim': args.lat_dim, # We fit args.lat_dim latent dimensions
        'n_feats': {'fundus': [3, args.ndf, args.fundus_img_size],
                    'cmr': [args.sax_img_size[2], args.ndf, args.sax_img_size[0]]
                    },
        'opt': args
    }

    print('\n --- Loading IDs files \n')

    # Reading the files that contains labels and names.
    test_set = pd.read_csv(args.dir_ids, sep=',')

    test_loader = MM_loader(batch_size=args.batch_size,
                            fundus_img_size=args.fundus_img_size,
                            num_workers=args.n_cpu,
                            shuffle=False,
                            dir_imgs=args.dir_dataset,
                            ids_set=test_set
                            )
    # Loading models
    print('\n --- Loading mcVAE model ...')
    # Creating model
    model_MM = pytorch_modules.MultiChannelSparseVAE(**init_dict)
    loaded_model = utilities.load_model(args.dir_weights_mcvae)
    model_MM.load_state_dict(loaded_model['state_dict'])

    print('\n --- Loading deep regressor model ...')

    model_reg = globals()[args.model_name](args = args)
    loaded_model = torch.load(os.path.join(args.dir_weights_regressor, args.model_name + '.tar'))
    model_reg.load_state_dict(loaded_model['state_dict'])
    model_reg = model_reg.cuda()
    model_reg.eval()

    print('\n --- Performing Inference ...')

    laten_vars_fundus = []
    laten_vars_cmr = []
    img_names_4_linear_reg = []
    labels_4_linear_reg = []

    if not os.path.exists(args.dir_results):
        os.makedirs(args.dir_results)

    all_preds = torch.FloatTensor().cuda()
    image_names = []

    for i, (fundus, sax, mtdt, img_names) in enumerate(test_loader):

        image_names.extend(img_names)
        fundus = fundus.cuda()
        # This is loading empty images
        sax = sax.cuda()
        mtdt = mtdt.cuda()

        print('Generating CMR from Fundus images...')
        # Getting predictions
        inputToLatent = model_MM.encode((fundus, sax))
        latent_vars = model_MM.sample_from(inputToLatent)
        predictions = model_MM.decode(latent_vars)

        print('Estimating cardiac indices ...')
        recons_cmr = predictions[0][1].loc
        preds = model_reg(recons_cmr, mtdt)
        # print(preds.cpu().detach().numpy())
        all_preds = torch.cat((all_preds, preds.data), 0)

    pred_file_name =  args.dir_results + args.dir_ids.split('/')[-1][:-4]  + '_preds.csv'
    save_output(image_names, all_preds, args, save_file = pred_file_name)

    print('\n --- Performing inference for MI using estimated LVEDV and LVM ...')
    # Performing Myocardial Prediction
    MI_prediciton(image_names, args)
