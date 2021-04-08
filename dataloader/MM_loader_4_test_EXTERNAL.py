import numpy as np
from PIL import Image
import torch.utils.data as data
import torch
from torchvision import transforms
import pandas as pd
from sklearn.preprocessing import MinMaxScaler, RobustScaler
import cv2

def scalRadius(img, scale):
    x = img[int(img.shape[0]/2),:,:].sum(1)
    r = (x > x.mean() / 10).sum() / 2
    if r < 0.001: # This is for the very black images
        r = scale*2
    s = scale*1.0/r
    return cv2.resize(img, (0,0), fx=s, fy=s)


def load_preprocess_img(dir_img):
    scale = 300
    a = cv2.imread(dir_img)
    a = scalRadius(a,scale)
    a = cv2.addWeighted(a,4,cv2.GaussianBlur(a, (0,0), scale/30), -4, 128)
    b = np.zeros(a.shape)
    cv2.circle(b, (int(a.shape[1]/2),int(a.shape[0]/2)), int(scale*0.9), (1,1,1), -1, 8, 0)
    a = a*b + 128*(1-b)
    img = Image.fromarray(np.array(a, dtype=np.int8), "RGB")
    return img


class MM(data.Dataset):
    """ Multi-Modal Dataset.
        dir_imgs (string): Root directory of dataset where images are located.
	    fundus_img_size (int): Size for fundus images. i.e. 256
        ids_set (pandas class):
    """

    def __init__(self,
                dir_imgs,
                fundus_img_size,
                ids_set
                ):

        self.img_names = []
        self.fundus_img_size = fundus_img_size
        self.mtdt = []
        # fundus image paths
        self.path_imgs_fundus = []
        # number of participants
        self.num_parti = 0

        scaler = MinMaxScaler()
        # scaler = RobustScaler()
        mtdt_dataframe = ids_set[['sex', 'dbpa', 'sbpa', 'ss', 'ads', 'bmi', 'age']]
        # mtdt_dataframe = ids_set[['sex', 'ss', 'bmi', 'age']]
        mtdt_scaled = pd.DataFrame(scaler.fit_transform(mtdt_dataframe), columns=mtdt_dataframe.columns)

        for idx, ID in enumerate(ids_set.values):
            self.num_parti = self.num_parti + 1
            # Reading all fundus images per patient
            img_id = dir_imgs + 'fundus/' + ID[0]
            # path for fundus images
            self.path_imgs_fundus.append(img_id)
            # Image names
            self.img_names.append(ID[0].split('.')[0])

            self.mtdt.append([mtdt_scaled['sex'][idx], mtdt_scaled['dbpa'][idx], mtdt_scaled['sbpa'][idx], mtdt_scaled['ss'][idx],
                              mtdt_scaled['ads'][idx], mtdt_scaled['bmi'][idx], mtdt_scaled['age'][idx]
                              ])
            # self.mtdt.append([mtdt_scaled['sex'][idx], mtdt_scaled['ss'][idx], mtdt_scaled['bmi'][idx], mtdt_scaled['age'][idx]])

        # Transform for fundus images
        self.transform_fundus = transforms.Compose([
                transforms.Resize((self.fundus_img_size, self.fundus_img_size)),
                transforms.ToTensor(),
            ])


    # Denotes the total number of samples
    def __len__(self):
        return len(self.path_imgs_fundus)

    # This generates one sample of data
    def __getitem__(self, index):
        """
        Args:
            index (int): Index

        Returns:
            tuple: (fundus, label, img_name, index)
        """

        # Loading fundus image
        # preprocessing
        fundus = load_preprocess_img(self.path_imgs_fundus[index])
        # resizing the images
        fundus_image = self.transform_fundus(fundus)
        # normalizing the images
        fundus_image = (fundus_image - torch.min(fundus_image))/(torch.max(fundus_image) - torch.min(fundus_image)) # Normalize between 0 and 1

        # DON'T CARE. This is done as the mcvae RECEIVES sax input as well, BUT SAX IMAGE ISN'T NEED FOR TESTING
        sax = np.zeros((15, 128, 128))
        ############

        return fundus_image, torch.FloatTensor(sax), torch.FloatTensor(self.mtdt[index]), self.img_names[index]


def MM_loader(batch_size,
              fundus_img_size,
              num_workers,
              shuffle,
              dir_imgs,
              ids_set):


    ######### Create class Dataset MM ########
    MM_dataset = MM(dir_imgs=dir_imgs,
                    fundus_img_size=fundus_img_size,
                    ids_set=ids_set)

    print('Found ' + str(len(MM_dataset)) + ' fundus images')

    # Dataloader
    data_loader = torch.utils.data.DataLoader(MM_dataset, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers)

    return data_loader
