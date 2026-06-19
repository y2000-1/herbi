import sys
sys.path.append('pix2pix')
from pix2pix.options.train_options import TrainOptions
from pix2pix.train import main

if __name__ == '__main__':
    opt = TrainOptions().parse()   # get training options
    main(opt)
