import numpy as np
import itertools
from astropy import stats, units, table
from astropy.io import fits

from scipy import ndimage

import logging

logger = logging.getLogger(__name__)

def find_mask_edges(flat_image, use_image_columns=slice(None), gauss_filter_sigma=3, sigma_clip_sigma=2, sigma_clip_iter=5):
    """
        Finding the mask edges with a gradient image

        Parameters
        ----------

        flat_image : ~numpy.ndarray
            Image (preferably a flat) to be used for finding the edges

    """

    gradient_image = np.diff(flat_image, axis=0)

    gradient_profile = ndimage.gaussian_filter(np.median(gradient_image[:, use_image_columns], axis=1),
                                               sigma=gauss_filter_sigma)

    clipped_gradient_profile = stats.sigma_clip(gradient_profile, sig=sigma_clip_sigma, iters=sigma_clip_iter, maout=True)

    peak_mask = clipped_gradient_profile.mask & (clipped_gradient_profile.data >= 0)
    trough_mask = clipped_gradient_profile.mask & (clipped_gradient_profile.data < 0)

    peaks = np.ma.MaskedArray(clipped_gradient_profile.data, mask=~peak_mask)
    troughs = np.ma.MaskedArray(clipped_gradient_profile.data, mask=~trough_mask)

    pixel_index = np.arange(len(peaks))
    lower_edge_groups = [list(group) for key, group in itertools.groupby(pixel_index, lambda x: peaks.mask[x])
                         if key==False]

    lower_edges = []
    for edge_group in lower_edge_groups:
        if len(edge_group) == 1:
            continue

        lower_edges.append(np.average(edge_group, weights=gradient_profile[edge_group]))

    lower_edges = np.array(lower_edges)

    upper_edge_groups = [list(group) for key, group in itertools.groupby(pixel_index, lambda x: troughs.mask[x])
                         if key==False]

    upper_edges = []
    for edge_group in upper_edge_groups:
        if len(edge_group) == 1:
            continue

        upper_edges.append(np.average(edge_group, weights=gradient_profile[edge_group]))

    upper_edges = np.array(upper_edges)

    return peaks, troughs, lower_edges, upper_edges


def cut_slits(data, mdf_table, uncertainty=None, mask=None, return_cut_image=False):

    #check if the table has been prepared
    if 'SECX1' not in mdf_table.colnames:
        raise ValueError('The supplied table has not been prepared')

    final_hdu_list = fits.HDUList()

    if return_cut_image:
        cut_image = data.copy()

    for i, (sec_x1, sec_x2, sec_y1, sec_y2) in enumerate(mdf_table['SECX1', 'SECX2', 'SECY1', 'SECY2']):
        current_slice = (slice(sec_y1, sec_y2), slice(sec_x1,sec_x2))
        data_slice = data[current_slice].copy()

        if return_cut_image:
            cut_image[current_slice] = - 1000

        final_hdu_list.append(fits.ImageHDU(data_slice, name='DATA_%d' % i))

        if uncertainty is not None:
            uncertainty_slice = uncertainty[current_slice]
            final_hdu_list.append(fits.ImageHDU(uncertainty_slice, name='UNCERTAINTY_%d' % i))

        if mask is not None:
            mask_slice = mask[current_slice]
            final_hdu_list.append(fits.ImageHDU(mask_slice, name='MASK_%d' % i))
    if return_cut_image:
        return cut_image, final_hdu_list
    else:
        return final_hdu_list


def prepare_mdf_table(mdf_table, naxis1, naxis2, x_scale, y_scale, anamorphic_factor, wavelength_offset, spectral_pixel_scale,
                wavelength_start, wavelength_central, wavelength_end, y_distortion_coefficients=[1, 0, 0],
                arcsecpermm = 1.611444 * units.Unit('arcsec/mm'), y_offset=0.0):
    """
    Prepares the MDF Table to reflect the pixel sections for the different slits

    Parameters
    ----------

    mdf_table : table like object (MDF)

    x_scale : ~astropy.units.Quantity
        in 'arcsec/pixel'

    y_scale : ~astropy.units.Quantity
        in 'arcsec/pixel'

    y_distortion_coefficients : ~np.ndarray
        y distortion correction coeffiencents in the form of coef[0] * y_pos + coef[1] * y_pos**2 + coef[2] * y_pos**3
        the coefficients are applied to the slits still in 'mm'


    """
    mdf_table = table.Table(mdf_table)
    slit_pos_mx, slit_pos_my = mdf_table['slitpos_mx'], mdf_table['slitpos_my']
    slit_pos_mx = slit_pos_mx * units.Unit('mm')
    slit_size_mx, slit_size_my = mdf_table['slitsize_mx'], mdf_table['slitsize_my']

    slit_size_mx = slit_size_mx.data * units.Unit('mm')
    slit_size_my = slit_size_my.data * units.Unit('mm')
    slit_length = slit_size_my * arcsecpermm

    logger.debug('Slit length')
    slit_width = slit_size_mx * arcsecpermm

    spectrum_width = np.round(1.05 * (slit_length / y_scale).to('pix').value).astype(int) * units.Unit('pix')
    logger.debug('Spectrum Width: %s', spectrum_width)
    spectrum_length = np.round(((wavelength_end - wavelength_start) / spectral_pixel_scale).to('pix').value).astype(int)\
                      * units.Unit('pix')
    logger.debug('Spectrum Length: %s', spectrum_length)

    wavelength_central_pixel = (spectrum_length - (wavelength_central - wavelength_start) / spectral_pixel_scale).\
        to('pix').value

    logger.debug('Spectrum Central Wavelength: %s', wavelength_central_pixel)


    corrected_ypos = (y_distortion_coefficients[0] * slit_pos_my.data +
                      y_distortion_coefficients[1] * slit_pos_my.data**2 +
                      y_distortion_coefficients[2] * slit_pos_my.data**3) * units.Unit('mm')

    x_center =  naxis1 / 2.
    y_center = naxis2 / 2.

    slit_pos_y = corrected_ypos * arcsecpermm / y_scale

    assert slit_pos_y.unit == units.Unit('pix')

    slit_pos_x = slit_pos_mx * arcsecpermm / x_scale

    assert slit_pos_x.unit == units.Unit('pix')

    logger.debug('X position relative to center: %s', slit_pos_x)
    logger.debug('Y position relative to center: %s', slit_pos_y)



    slit_pos_x = slit_pos_x.value + x_center
    slit_pos_y = slit_pos_y.value + y_center

    #Simple correction for distortion in x
    y = (slit_pos_y / naxis2) - 0.5
    distortion_x = naxis1 *  (0.0014 * y - 0.0167 * y**2)
    logger.debug('y=%s distortion_x=%s', y, distortion_x)



    x1 = (np.round(x_center - ((x_center - slit_pos_x) / anamorphic_factor) - wavelength_central_pixel) + \
         (wavelength_offset / spectral_pixel_scale).to('pix').value + distortion_x).astype(int)
    x2 = x1 + spectrum_length #Check if -1 is needed


    y1 = (np.round(slit_pos_y - spectrum_width.value/2 + y_offset.value)).astype(int)
    y2 = y1 + spectrum_width.value
    logger.debug('pre check x1=%s x2=%s y1=%s y2=%s', x1, x2, y1, y2)

    refpix = np.ones_like(x1) * wavelength_central_pixel
    refpix[x1 < 0] += x1
    x1[x1 < 0] = 0
    x2[x2 > naxis1] = naxis1

    y1[y1 < 0] = 0
    y2[y2 > naxis2] = naxis2

    logger.debug('post check x1=%s x2=%s y1=%s y2=%s', x1, x2, y1, y2)

    mdf_table['SECX1'] = x1
    mdf_table['SECX2'] = x2
    mdf_table['SECY1'] = y1
    mdf_table['SECY2'] = y2
    mdf_table['REFPIX1'] = refpix
    #Debug information

    return mdf_table








