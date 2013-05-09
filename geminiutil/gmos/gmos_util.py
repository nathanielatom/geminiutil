import os, yaml
from astropy import units as u

gmos_data_dir = os.path.join(os.path.dirname(__file__), 'data')
default_gmos_configuration_fname = os.path.join(gmos_data_dir, 'gmos_configuration.yml')


def parse_readout_direction(detector_readout):
    """ Parameter: detector_readout - string to be parsed for direction component
    Returns: a string for direction component - e.g. "EEV 2037-06-03, left" parses to "left".
    """
    return detector_readout.split()[-1]


class MissingFITSInformation(ValueError):
    pass


class DetectorGeometry(object):
    """
    Read detector geometry
    """

    def __init__(self, fits_object, gmos_configuration_fname=None):
        if gmos_configuration_fname is None:
            gmos_configuration_fname = default_gmos_configuration_fname
        self.gmos_configuration = yaml.load(file(gmos_configuration_fname))

        if 'dettype' not in fits_object.header:
            raise MissingFITSInformation('"dettype" not present in header - needed for geometry')

        self.detector_type = dict((v, k) for k,v in self.gmos_configuration['detector_type'].iteritems())[fits_object.header['dettype']]

        self.instrument = fits_object.header['instrume'].lower()
        self.generic_pixelscale = u.Quantity.parse_string(
                                        self.gmos_configuration['pixel_scale'][self.instrument][self.detector_type])
        #looping through the chips to get the binning information
        self.y_pixel_scale = []
        self.x_pixel_scale = []
        for i in xrange(3):
            current_ccd = fits_object.fits_data[i+1]
            if 'CCDSUM' not in current_ccd.header:
                raise MissingFITSInformation('"CCDSUM" not present in header of chip %d - needed for geometry' % i)
            x_binning, y_binning = map(int, current_ccd.header['CCDSUM'].split())

            self.x_pixel_scale.append(x_binning * self.generic_pixelscale)
            self.y_pixel_scale.append(y_binning * self.generic_pixelscale)





