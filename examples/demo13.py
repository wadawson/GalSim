# Copyright (c) 2012-2014 by the GalSim developers team on GitHub
# https://github.com/GalSim-developers
#
# This file is part of GalSim: The modular galaxy image simulation toolkit.
# https://github.com/GalSim-developers/GalSim
#
# GalSim is free software: redistribution and use in source and binary forms,
# with or without modification, are permitted provided that the following
# conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions, and the disclaimer given in the accompanying LICENSE
#    file.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions, and the disclaimer given in the documentation
#    and/or other materials provided with the distribution.
#
"""
Demo #13

The thirteenth script in our tutorial about using Galsim in python scripts: examples/demo*.py.
(This file is designed to be viewed in a window 100 characters wide.)

This script currently doesn't have an equivalent demo*.yaml or demo*.json file.

This script introduces the non-idealities arising from the (NIR) detectors, in particular those
that will be observed and accounted for in the WFIRST surveys. Four such non-ideal effects are
demonstrated, in the order in which they are introduced in the detectors:

1) Reciprocity Failure: Flux dependent sensitivity of the detector
2) Dark current: Constant response to zero flux, due to thermal generation of electron-hole pairs.
3) Non-linearity: Charge dependent gain in converting from units of electrons to ADU.
4) Interpixel Capacitance: Influence of charge in a pixel on the voltage reading of neighboring
   ones.

The purpose of the demo is two-fold: to show the effects of detector non-idealities in the full
context of the entire image generation process., including all sources of noise and skylevel added
at appropriate stages. After each effect, suggested parameters for viewing the intermediate and
difference images in ds9 are also included.

New feautres introduced in this demo:
- Adding sky level and dark current
- poisson_noise = galsim.PoissonNoise(rng)
- image.addReciprocityFailure(exp_time, alpha, base_flux)
- image.applyNonlinearity(NLfunc,*args)
- image.applyIPC(IPC_kernel, edge_treatment, fill_value, kernel_nonnegativity,
                 kernel_normalization)
- readnoise = galsim.CCDNoise(rng)
- readnoise.setReadNoise(readnoise_level)
"""

import numpy
import sys, os
import math
import logging
import galsim as galsim
import galsim.wfirst as wfirst

def main(argv):
    # Where to find and output data.
    path, filename = os.path.split(__file__)
    datapath = os.path.abspath(os.path.join(path, "data/"))
    outpath = os.path.abspath(os.path.join(path, "output/"))

    # In non-script code, use getLogger(__name__) at module scope instead.
    logging.basicConfig(format="%(message)s", level=logging.INFO, stream=sys.stdout)
    logger = logging.getLogger("demo13")

    # Initialize (pseudo-)random number generator.
    random_seed = 1234567
    rng = galsim.BaseDeviate(random_seed)

    # Generate a Poisson noise model.
    poisson_noise = galsim.PoissonNoise(rng) 
    logger.info('Poisson Noise model created')

    # Read in the WFIRST filters.
    filters = wfirst.getBandpasses(AB_zeropoint=True)
    # We care about the NIR imaging, not the prism and grism, so let's remove them:
    del filters['SNPrism']
    del filters['BAO-Grism']
    logger.debug('Read in filters')

    # Read in SEDs.  We only need two of them, for the two components of the galaxy (bulge and
    # disk).
    SED_names = ['CWW_E_ext', 'CWW_Im_ext']
    SEDs = {}
    for SED_name in SED_names:
        SED_filename = os.path.join(datapath, '{0}.sed'.format(SED_name))
        SED = galsim.SED(SED_filename, wave_type='Ang')

        # The normalization of SEDs affects how many photons are eventually drawn into an image.
        # One way to control this normalization is to specify the magnitude in a given bandpass
        # filter. We pick W149 and enforce the flux through the filter to be of magnitude specified
        # by `mag_norm`.  This choice is overall normalization is completely arbitrary, but it means
        # that the colors of the galaxy will now be meaningful (for example, the bulge will be more
        # evident in the redder bands and the disk in the bluer bands).
        bandpass = filters['W149']
        mag_norm = 22.0

        SEDs[SED_name] = SED.withMagnitude(target_magnitude=mag_norm, bandpass=bandpass)

    logger.debug('Successfully read in SEDs')

    logger.info('')
    redshift = 0.8
    logger.info('Simulating a chromatic bulge+disk galaxy at z=%.1f'%redshift)

    # Make a bulge.  We will use a size that is fairly large compared to the WFIRST pixel scale.
    pixel_scale = wfirst.pixel_scale
    mono_bulge = galsim.DeVaucouleurs(half_light_radius=5.*pixel_scale)
    bulge_SED = SEDs['CWW_E_ext'].atRedshift(redshift)
    bulge = mono_bulge * bulge_SED
    bulge = bulge.shear(g1=0.12, g2=0.07)
    logger.debug('Created bulge component.')
    # Now make the disk.  Its half-light-radius is somewhat larger and it is more flattened than the
    # bulge component.
    mono_disk = galsim.Exponential(half_light_radius=8.*pixel_scale)
    disk_SED = SEDs['CWW_Im_ext'].atRedshift(redshift)
    disk = mono_disk * disk_SED
    disk = disk.shear(g1=0.4, g2=0.2)
    logger.debug('Created disk component')
    # Combine them, giving a bulge-to-total flux ratio of 1/3 in the band used for the
    # normalization (W149).
    bdgal = bulge + 2.*disk

    # At this stage, our galaxy is chromatic.
    logger.debug('Created bulge+disk galaxy final profile')

    # Here we carry out the initial steps that are necessary to get a fully chromatic PSF.  We use
    # the getPSF() routine in the WFIRST module, which knows all about the telescope parameters
    # (diameter, bandpasses, obscuration, etc.).  Note that we are going to arbitrarily choose a
    # single SCA rather than all of them, for faster calculations, and we're going to use a simpler
    # representation of the struts for faster calculations.  To do a more exact calculation of the
    # chromaticity and pupil plane configuration, remove the approximate_struts and the n_waves
    # keyword from this call:
    use_SCA = 7 # This could be any number from 1...18
    logger.info('Doing expensive pre-computation of PSF')
    PSFs = wfirst.getPSF(SCAs=use_SCA, approximate_struts=True, n_waves=25)
    PSF = PSFs[use_SCA]
    logger.info('Done precomputation!')

    # Load WFIRST parameters
    exptime = wfirst.exptime # 168.1 seconds

    # draw profile through WFIRST filters
    for filter_name, filter_ in filters.iteritems():        
        # Drawing PSF.  Note that the PSF object intrinsically has a flat SED, so if we convolve it
        # with a galaxy, it will properly take on the SED of the galaxy.  However, this does mean
        # that the PSF image being drawn here is not quite the right PSF for the galaxy.  Indeed,
        # the PSF for the galaxy effectively varies within it, since it differs for the bulge and
        # the disk.  However, the WFIRST bandpasses are narrow enough that this doesn't matter too
        # much.
        out_filename = os.path.join(outpath, 'demo13_PSF_{0}.fits'.format(filter_name))
        img_psf = PSF.drawImage(filter_, scale=pixel_scale)
        img_psf.write(out_filename)
        logger.debug('Created PSF with flat SED for {0}-band'.format(filter_name))

        # Convolve galaxy with PSF
        bdconv = galsim.Convolve([bdgal, PSF])

        img = galsim.ImageF(512/8,512/8, scale=pixel_scale) # 64, 64
        bdconv.drawImage(filter_, image=img)

        # Adding sky level to the image.  First we get the amount of zodaical light (where currently
        # we use the default location on the sky; this value will depend on position).  Since we
        # have supplied an exposure time, the results will be returned to us in e-/s.  Then we
        # multiply this by a factor to account for the amount of stray light that is expected.
        sky_level_pix = wfirst.getSkyLevel(filters[filter_name], exp_time=wfirst.exptime)
        sky_level_pix *= (1.0 + wfirst.stray_light_fraction)
        # Finally we add the expected thermal backgrounds in this band.  These are provided in
        # e-/pix/s, so we have to multiply by the exposure time.
        sky_level_pix += wfirst.thermal_backgrounds[filter_name]*wfirst.exptime
        img += sky_level_pix
        print "sky_level_pix = ", sky_level_pix

        #Adding Poisson Noise       
        img.addNoise(poisson_noise)

        logger.debug('Created {0}-band image'.format(filter_name))
        out_filename = os.path.join(outpath, 'demo13_{0}.fits'.format(filter_name))
        img.write(out_filename)
        logger.debug('Wrote {0}-band image to disk'.format(filter_name))

        # The subsequent steps account for the non-ideality of the detectors

        # Accounting Reciprocity Failure:
        # Reciprocity, in the context of photography, is the inverse relationship between the
        # incident flux (I) of a source object and the exposure time (t) required to produce a
        # given response(p) in the detector, i.e., p = I*t. However, in NIR detectors, this
        # relation does not hold always. The pixel response to a high flux is larger than its
        # response to a low flux. This flux-dependent non-linearity is known as 'Reciprocity
        # Failure'.

        # Save the image before applying the transformation to see the difference
        img_old = img.copy()

        img.addReciprocityFailure(exp_time=exptime,alpha=wfirst.reciprocity_alpha,base_flux=1.0)
        logger.debug('Accounted for Reciprocity Failure in {0}-band image'.format(filter_name))
        out_filename = os.path.join(outpath, 'demo13_RecipFail_{0}.fits'.format(filter_name))
        img.write(out_filename)
        out_filename = os.path.join(outpath, 'demo13_diff_RecipFail_{0}.fits'.format(filter_name))
        diff = img-img_old
        diff.write(out_filename)
        logger.debug('Wrote {0}-band image  after Recip. Failure to disk'.format(filter_name))

        # Adding dark current to the image
        # Even when the detector is unexposed to any radiation, the electron-hole pairs that are
        # generated within the depletion region due to finite temperature are swept by the high
        # electric field at the junction of the photodiode. This small reverse bias leakage current
        # is referred to as 'Dark current'. It is specified by the average number of electrons
        # reaching the detectors per unit time and has an associated Poisson noise since it's a
        # random event.
        dark_img = galsim.ImageF(bounds=img.bounds, init_value=wfirst.dark_current*wfirst.exptime)
        dark_img.addNoise(poisson_noise)
        img += dark_img

        # NOTE: Sky level and dark current might appear like a constant background that can be
        # simply subtracted. However, these contribute to the shot noise and matter for the
        # non-linear effects that follow. Hence, these must be included at this stage of the image
        # generation process. We subtract these backgrounds in the end.

        # Applying a quadratic non-linearity
        # In order to convert the units from electrons to ADU, we must multiply the image by a
        # gain factor. The gain has a weak dependency on the charge present in each pixel. This
        # dependency is accounted for by changing the pixel values (in electrons) and applying a
        # constant nominal gain later, which is unity in our demo.

        # Save the image before applying the transformation to see the difference
        img_old = img.copy()

        NLfunc = wfirst.NLfunc        # a quadratic non-linear function
        img.applyNonlinearity(NLfunc)
        logger.debug('Applied Nonlinearity to {0}-band image'.format(filter_name))
        out_filename = os.path.join(outpath, 'demo13_NL_{0}.fits'.format(filter_name))
        img.write(out_filename)
        out_filename = os.path.join(outpath, 'demo13_diff_NL_{0}.fits'.format(filter_name))
        diff = img-img_old
        diff.write(out_filename)
        logger.debug('Wrote {0}-band image with Nonlinearity to disk'.format(filter_name))

        # Adding Interpixel Capacitance
        # The voltage read at a given pixel location is influenced by the charges present in the
        # neighboring pixel locations due to capacitive coupling of sense nodes. This interpixel
        # capacitance effect is modelled as a linear effect that is described as a convolution of a
        # 3x3 kernel with the image. The WFIRST kernel is not normalized to have the entries add to
        # unity and hence must be normalized inside the routine.

        # Save the image before applying the transformation to see the difference
        img_old = img.copy()

        img.applyIPC(IPC_kernel=wfirst.ipc_kernel,edge_treatment='extend',
                     kernel_normalization=True)
        # Here, we use `edge_treatment='extend'`, which pads the image with zeros before applying
        # the kernel. The central part of the image is retained.
        logger.debug('Applied interpixel capacitance to {0}-band image'.format(filter_name))
        out_filename = os.path.join(outpath, 'demo13_IPC_{0}.fits'.format(filter_name))
        img.write(out_filename)
        out_filename = os.path.join(outpath, 'demo13_diff_IPC_{0}.fits'.format(filter_name))
        diff = img-img_old
        diff.write(out_filename)
        logger.debug('Wrote {0}-band image with IPC to disk'.format(filter_name))

        # Adding Read Noise
        read_noise = galsim.CCDNoise(rng)
        read_noise.setReadNoise(wfirst.read_noise)
        img.addNoise(read_noise)

        logger.debug('Added Readnoise to {0}-band image'.format(filter_name))
        out_filename = os.path.join(outpath, 'demo13_ReadNoise_{0}.fits'.format(filter_name))
        img.write(out_filename)
        logger.debug('Wrote {0}-band image with readnoise to disk'.format(filter_name))

        # Subtracting backgrounds
        img -= sky_level_pix
        img -= wfirst.dark_current*wfirst.exptime

        logger.debug('Added Readnoise for {0}-band image'.format(filter_name))
        out_filename = os.path.join(outpath, 'demo13_{0}.fits'.format(filter_name))
        img.write(out_filename)
        logger.debug('Wrote the final {0}-band image after subtracting backgrounds to disk'.\
                     format(filter_name))

    logger.info('You can display the output in ds9 with a command line that looks something like:')
    logger.info('ds9 -rgb -blue -scale limits -0.2 0.8 output/demo13_J129.fits -green '
        +'-scale limits'+' -0.25 1.0 output/demo13_W149.fits -red -scale limits -0.25'
        +' 1.0 output/demo13_Z087.fits -zoom 2 &')

if __name__ == "__main__":
    main(sys.argv)
