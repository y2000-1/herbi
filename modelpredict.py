import sys
import os
import tempfile
import shutil
from argparse import Namespace

sys.path.append('pix2pix')
from pix2pix.options.test_options import TestOptions
from pix2pix.predict import main


def make_predict_opt(dataroot, name='universal', checkpoints_dir='./model_saved',
                     results_dir='./imgs_predicted/', gpu_ids=None):
    """
    Build an opt Namespace for pix2pix prediction without argparse.

    Args:
        dataroot: Path to standardized images directory (must contain a 'test' subfolder).
        name: Model/experiment name (subfolder under checkpoints_dir).
        checkpoints_dir: Path to saved model weights.
        results_dir: Path to save prediction results.
        gpu_ids: List of GPU ids, e.g. [0]. Empty list [] or [-1] for CPU.

    Returns:
        argparse.Namespace with all required options.
    """
    if gpu_ids is None:
        gpu_ids = []

    opt = Namespace(
        # --- core ---
        dataroot=str(dataroot),
        name=name,
        checkpoints_dir=str(checkpoints_dir),
        results_dir=str(results_dir),
        model='test',
        netG='unet_256',
        norm='batch',
        isTrain=False,
        gpu_ids=gpu_ids,
        # --- network ---
        input_nc=3,
        output_nc=3,
        ngf=64,
        ndf=64,
        netD='basic',
        n_layers_D=3,
        no_dropout=False,
        init_type='normal',
        init_gain=0.02,
        # --- dataset ---
        dataset_mode='single',
        direction='BtoA',
        serial_batches=True,
        num_threads=0,
        batch_size=1,
        load_size=256,
        crop_size=256,
        max_dataset_size=float('inf'),
        preprocess='resize_and_crop',
        no_flip=True,
        # --- test / output ---
        phase='test',
        epoch='latest',
        load_iter=0,
        num_test=50,
        eval=False,
        display_winsize=256,
        display_id=-1,
        aspect_ratio=1.0,
        verbose=False,
        suffix='',
        model_suffix='',
        use_wandb=False,
        wandb_project_name='CycleGAN-and-pix2pix',
    )
    return opt


def predict_from_images(images, model_name='universal',
                        checkpoints_dir='./model_saved',
                        gpu_ids=None, project_root=None):
    """
    Run pix2pix prediction on a list of 256x256 BGR numpy images.

    Args:
        images: List of (filename, ndarray) tuples. Each ndarray is 256x256 BGR.
        model_name: Name of the saved model experiment.
        checkpoints_dir: Path to model checkpoints.
        gpu_ids: GPU ids list, [] for CPU.
        project_root: Project root directory (for resolving pix2pix paths).

    Returns:
        List of dicts: [{'name': str, 'real': ndarray, 'fake': ndarray}, ...]
    """
    import cv2
    import numpy as np

    if project_root is None:
        project_root = os.path.dirname(os.path.abspath(__file__))

    with tempfile.TemporaryDirectory(prefix='herbiestim_pred_') as tmpdir:
        # Write images to temp dataroot/test/
        test_dir = os.path.join(tmpdir, 'dataroot', 'test')
        os.makedirs(test_dir, exist_ok=True)
        for fname, img in images:
            cv2.imwrite(os.path.join(test_dir, fname), img)

        results_dir = os.path.join(tmpdir, 'results')

        opt = make_predict_opt(
            dataroot=os.path.join(tmpdir, 'dataroot'),
            name=model_name,
            checkpoints_dir=os.path.join(project_root, checkpoints_dir)
                if not os.path.isabs(checkpoints_dir) else checkpoints_dir,
            results_dir=results_dir,
            gpu_ids=gpu_ids,
        )
        opt.num_test = len(images)

        # Run pix2pix prediction
        main(opt)

        # Collect results
        img_dir = os.path.join(results_dir, model_name, 'test_latest', 'images')
        results = []
        for fname, _ in images:
            stem = os.path.splitext(fname)[0]
            real_path = os.path.join(img_dir, f'{stem}_real.png')
            fake_path = os.path.join(img_dir, f'{stem}_fake.png')
            real_img = cv2.imread(real_path) if os.path.exists(real_path) else None
            fake_img = cv2.imread(fake_path) if os.path.exists(fake_path) else None
            results.append({'name': fname, 'real': real_img, 'fake': fake_img})

        return results


if __name__ == '__main__':
    opt = TestOptions().parse()  # get test options

    img = os.listdir(os.path.join(opt.dataroot, 'test'))
    if '.DS_Store' in img:
        img.remove('.DS_Store')
    opt.num_test = len(img)
    opt.netG = 'unet_256'
    opt.norm = 'batch'
    main(opt)
