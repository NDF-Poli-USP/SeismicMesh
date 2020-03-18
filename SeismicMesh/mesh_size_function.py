# -----------------------------------------------------------------------------
#  Copyright (C) 2020 Keith Jared Roberts

#  Distributed under the terms of the GNU General Public License. You should
#  have received a copy of the license along with this program. If not,
#  see <http://www.gnu.org/licenses/>.
# -----------------------------------------------------------------------------
from scipy.interpolate import RegularGridInterpolator
import numpy as np
import matplotlib.pyplot as plt

import segyio

from SeismicMesh.FastHJ import limgrad


def drectangle(p, x1, x2, y1, y2):
    min = np.minimum
    """Signed distance function for rectangle with corners (x1,y1), (x2,y1),
    (x1,y2), (x2,y2).
    This has an incorrect distance to the four corners but that isn't a big deal
    """
    return -min(min(min(-y1 + p[:, 1], y2 - p[:, 1]), -x1 + p[:, 0]), x2 - p[:, 0])


def hj(fun, elen, grade, imax):
    """ Call-back to the cpp gradient limiter code """
    _nz, _nx = np.shape(fun)
    ffun = fun.flatten("F")
    ffun_list = ffun.tolist()
    tmp = limgrad([_nz, _nx, 1], elen, grade, imax, ffun_list)
    tmp = np.asarray(tmp)
    fun_s = np.reshape(tmp, (_nz, _nx), "F")
    return fun_s


class MeshSizeFunction:
    """
    MeshSizeFunction: build an isotropic mesh size function for seismic domains.

    Usage
    -------
    >>>> obj = MeshSizeFunction(bbox,hmin,segy,**kwargs)


    Parameters
    -------
        bbox: Bounding box, (xmin, xmax, ymin, ymax)
        hmin: Minimum triangular edgelength populating domain, (meters)
        model: (2D) Seg-y file containing velocity model, (assumes velocity is in METERS PER SECOND)
                                                OR
        (3D) binary file containing velocity model, (assumes velocity is in METERS PER SECOND)
             -Litte endian.
             -Requires to specify number of grid points in each dimension. nx, ny, and nz.

                                **kwargs
        nx: for velocity model, number of grid points in x-direction
        ny: for velocity model, number of grid points in y-direction
        nz: for velocity model, number of grid points in z-direction
        units: velocity is in either m-s or km-s (default='m-s')
        wl:   number of nodes per wavelength for given max. freq, (num. of nodes per wl., default=disabled)
        freq: maximum source frequency for which to estimate wl (hertz, default=disabled)
        hmax: maximum edgelength in the domain (meters, default=disabled)
        dt: maximum stable timestep (in seconds given Courant number cr, default=disabled)
        cr_max: dt is theoretically stable with this Courant number (default=0.2)
        grade: maximum allowable variation in mesh size (default=disabled)


    Returns
    -------
        MeshSizeFunction object


    Example
    ------
    import SeismicMesh
    # In 2D
    ef = SeismicMesh.MeshSizeFunction(
            bbox=(-12e3,0,0,67e3),
            ,model=fname,
            hmin=2e3
            # ,wl=5,freq=5
            # ,hmax=4e3
            # ,grade=10.0
            # ,dt=0.001
            # ,cr_max=0.1
            )

    """

    def __init__(
        self,
        bbox,
        hmin,
        model,
        units="m-s",
        wl=0.0,
        freq=5.0,
        hmax=np.inf,
        dt=0.0,
        cr_max=0.2,
        grade=0.0,
    ):
        self.bbox = bbox
        self.hmin = hmin
        self.model = model
        self.units = units
        self.wl = wl
        self.freq = freq
        self.hmax = hmax
        self.dt = dt
        self.cr_max = cr_max
        self.grade = grade
        self.nz = None
        self.ny = None
        self.nx = None
        self.fh = None
        self.fd = None

    ### SETTERS AND GETTERS ###

    @property
    def fh(self):
        return self.__fh

    @fh.setter
    def fh(self, value):
        self.__fh = value

    @property
    def fd(self):
        return self.__fd

    @fd.setter
    def fd(self, value):
        self.__fd = value

    @property
    def bbox(self):
        return self.__bbox

    @bbox.setter
    def bbox(self, value):
        assert len(value) >= 4 and len(value) <= 6, "bbox has wrong number of args"
        self.__bbox = value

    @property
    def hmin(self):
        return self.__hmin

    @hmin.setter
    def hmin(self, value):
        assert value > 0.0, "hmin must be non-zero"
        self.__hmin = value

    @property
    def vp(self):
        return self.__vp

    @vp.setter
    def vp(self, value):
        self.__vp = value

    @property
    def nz(self):
        assert self.__nz is not None, "binary file specified but nz was not."
        return self.__nz

    @nz.setter
    def nz(self, value):
        self.__nz = value

    @property
    def nx(self):
        assert self.__nx is not None, "binary file specified but nx was not."
        return self.__nx

    @nx.setter
    def nx(self, value):
        self.__nx = value

    @property
    def ny(self):
        assert self.__ny is not None, "binary file specified but ny was not."
        return self.__ny

    @ny.setter
    def ny(self, value):
        self.__ny = value

    @property
    def model(self):
        return self.__model

    @model.setter
    def model(self, value):
        assert isinstance(value, str) is True, "model must be a filename"
        self.__model = value

    @property
    def units(self):
        return self.__units

    @units.setter
    def units(self, value):
        assert value == "m-s" or value == "km-s", "units are not compatible"
        self.__units = value

    @property
    def wl(self):
        return self.__wl

    @wl.setter
    def wl(self, value):
        self.__wl = value

    @property
    def freq(self):
        return self.__freq

    @freq.setter
    def freq(self, value):
        self.__freq = value

    @property
    def hmax(self):
        return self.__hmax

    @hmax.setter
    def hmax(self, value):
        self.__hmax = value

    @property
    def dt(self):
        return self.__dt

    @dt.setter
    def dt(self, value):
        assert value >= 0, "dt must be > 0"
        self.__dt = value

    @property
    def cr_max(self):
        return self.__cr_max

    @cr_max.setter
    def cr_max(self, value):
        self.__cr_max = value

    @property
    def grade(self):
        return self.__grade

    @grade.setter
    def grade(self, value):
        self.__grade = value

    # ---PUBLIC METHODS---#

    def build(self):
        """Builds the isotropic mesh size function according
            to the user arguments that were passed.

        Usage
        -------
        >>>> obj = build(self)


        Parameters
        -------
            MeshSizeFunction object

         Returns
        -------
            SeismicMesh.MeshSizeFunction object with specific fields populated:
                self.fh: lambda function w/ scipy.inerpolate.RegularGridInterpolater representing isotropic mesh sizes in domain
                self.fd: lambda function representing the signed distance function of domain

        """
        _bbox = self.bbox
        width = max(_bbox)
        _vp, _nz, _nx = self.__ReadVelocityModel()

        self.vp = _vp
        self.nz = _nz
        self.nx = _nx

        _hmax = self.hmax
        _hmin = self.hmin
        _grade = self.grade

        _wl = self.wl
        _freq = self.freq

        _dt = self.dt
        _cr_max = self.cr_max

        hh_m = np.zeros(shape=(_nz, _nx)) + _hmin
        if _wl > 0:
            print(
                "Mesh sizes with be built to resolve an estimate of wavelength with "
                + str(_wl)
                + " vertices..."
            )
            hh_m = _vp / (_freq * _wl)
        # enforce min (and optionally max) sizes
        hh_m = np.where(hh_m < _hmin, _hmin, hh_m)
        if _hmax < np.inf:
            print("Enforcing maximum mesh resolution...")
            hh_m = np.where(hh_m > _hmax, _hmax, hh_m)
        # grade the mesh sizes
        if _grade > 0:
            print("Enforcing mesh gradation...")
            hh_m = hj(hh_m, width / _nx, _grade, 10000)
        # adjust based on the CFL limit so cr < cr_max
        if _dt > 0:
            print("Enforcing timestep of " + str(_dt) + " seconds...")
            cr_old = (_vp * _dt) / hh_m
            dxn = (_vp * _dt) / _cr_max
            hh_m = np.where(cr_old > _cr_max, dxn, hh_m)

        # construct a interpolator object to be queried during mesh generation
        z_vec, x_vec = self.__CreateDomainVectors()
        assert np.all(hh_m > 0.0), "edge_size_function must be strictly positive."
        interpolant = RegularGridInterpolator(
            (z_vec, x_vec), hh_m, bounds_error=False, fill_value=None
        )
        # create a mesh size function interpolant
        self.fh = lambda p: interpolant(p)

        def fdd(p):
            return drectangle(p, _bbox[0], _bbox[1], _bbox[2], _bbox[3])

        # create a signed distance function
        self.fd = lambda p: fdd(p)
        return self

    def plot(self, stride=5):
        """ Plot the isotropic mesh size function

        Usage
        -------
        >>>> plot(self)


        Parameters
        -------
            self: SeismicMesh.MeshSizeFunction object
                        **kwargs
            stride: downsample the image by n (n=5 by default)

         Returns
        -------
            none
            """
        fh = self.fh
        zg, xg = self.__CreateDomainMatrices()
        sz1z, sz1x = zg.shape
        sz2 = sz1z * sz1x
        _zg = np.reshape(zg, (sz2, 1))
        _xg = np.reshape(xg, (sz2, 1))
        hh = fh((_zg, _xg))
        hh = np.reshape(hh, (sz1z, sz1x))
        plt.pcolormesh(xg[0::stride], zg[0::stride], hh[0::stride], edgecolors="none")
        plt.title("Isotropic mesh sizes")
        plt.colorbar(label="mesh size (m)")
        plt.xlabel("x-direction (km)")
        plt.ylabel("z-direction (km)")
        plt.axis("equal")
        plt.show()
        return None

    def GetDomainMatrices(self):
        """ Accessor to private method"""
        zg, xg = self.__CreateDomainMatrices()
        return zg, xg

    # ---PRIVATE METHODS---#

    def __ReadVelocityModel(self):
        """ Reads a velocity model from a SEG-Y file (2D) or a binary file (3D). Uses the python package segyio."""
        _fname = self.model
        # determine type of file
        isSegy = _fname.lower().endswith((".segy"))
        isBin = _fname.lower().endswith((".bin"))
        if isSegy:
            print("Found SEG-Y file")
            with segyio.open(_fname, ignore_geometry=True) as f:
                # determine dimensions of velocity model from trace length
                nz = len(f.samples)
                nx = len(f.trace)
                vp = np.zeros(shape=(nz, nx))
                index = 0
                for trace in f.trace:
                    vp[:, index] = trace
                    index += 1
                vp = np.flipud(vp)
        elif isBin:
            print("Found binary file")
            nx = self.nx
            ny = self.ny
            nz = self.nz
            with open(_fname, "r") as file:
                vp = np.fromfile(file, dtype=np.dtype("float32").newbyteorder(">"))
                vp = vp.reshape(nx, ny, nz, order="F")
        else:
            print("Did not recognize file type...either .bin or .segy")
            quit()
        if self.__units == "km-s":
            print("Converting model velocities to m-s...")
            vp *= 1e3
        assert np.amin(vp) > 1000, "Min. velocity too low. Units may be incorrect."
        return vp, nz, nx

    def __CreateDomainVectors(self):
        _bbox = self.bbox
        _nx = self.nx
        _nz = self.nz
        width = max(_bbox)
        depth = min(_bbox)
        xvec = np.linspace(0, width, _nx)
        zvec = np.linspace(depth, 0, _nz)
        return zvec, xvec

    def __CreateDomainMatrices(self):
        zvec, xvec = self.__CreateDomainVectors()
        zg, xg = np.meshgrid(zvec, xvec, indexing="ij")
        return zg, xg
