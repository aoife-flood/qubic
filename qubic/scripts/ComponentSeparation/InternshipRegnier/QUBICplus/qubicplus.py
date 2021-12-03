from qubic import camb_interface as qc
import healpy as hp
import numpy as np
import qubicplus
import pysm3
import pysm3.units as u
from pysm3 import utils
from qubic import camb_interface as qc
import matplotlib.pyplot as plt
import os
import random as rd
import string
import qubic
from importlib import reload
import s4bi
from fgbuster.component_model import (CMB, Dust, Dust_2b, Synchrotron, AnalyticComponent)
from scipy import constants

def eval_scaled_dust_dbmmb_map(nu_ref, nu_test, beta0, beta1, nubreak, nside, fsky, radec_center, temp):
    #def double-beta dust model
    analytic_expr = s4bi.double_beta_dust_FGB_Model()
    dbdust = AnalyticComponent(analytic_expr, nu0=nu_ref, h_over_k=constants.h * 1e9 / constants.k, temp=temp)
    scaling_factor = dbdust.eval(nu_test, beta0, beta1, nubreak)

    sky=pysm3.Sky(nside=nside, preset_strings=['d0'])
    dust_map_ref = np.zeros((3, 12*nside**2)) #this way the output is w/0 units!!
    dust_map_ref[0:3,:]=sky.get_emission(nu_ref*u.GHz, None)*utils.bandpass_unit_conversion(nu_ref*u.GHz,None, u.uK_CMB)


    map_test=dust_map_ref*scaling_factor

    mask = s4bi.get_coverage(fsky, nside, center_radec=radec_center)

    return map_test

def get_scaled_dust_dbmmb_map(nu_ref, nu_vec, beta0, beta1, nubreak, nside, fsky, radec_center, temp):
    #eval at each freq. In this way it can be called both in the single-freq and the multi-freq case
    n_nu=len(nu_vec)
    dust_map= np.zeros((n_nu, 3, 12*nside**2))
    for i in range(n_nu):
        map_eval=eval_scaled_dust_dbmmb_map(nu_ref, nu_vec[i], beta0, beta1, nubreak, nside, fsky, radec_center, temp)
        #hp.mollview(map_eval[1])
        dust_map[i,:,:]=map_eval[:,:]
    return dust_map

def theoretical_noise_maps(sigma_sec, coverage, Nyears=4, verbose=False):
    """
    This returns a map of the RMS noise (not an actual realization, just the expected RMS - No covariance)

    Parameters
    ----------
    sigma_sec: float
        Noise level.
    coverage: array
        The coverage map.
    Nyears: int
    verbose: bool

    Returns
    -------

    """
    # ###### Noise normalization
    # We assume we have integrated for a time Ttot in seconds with a sigma per root sec sigma_sec
    Ttot = Nyears * 365 * 24 * 3600  # in seconds
    if verbose:
        print('Total time is {} seconds'.format(Ttot))
    # Oberved pixels
    thepix = coverage > 0
    # Normalized coverage (sum=1)
    covnorm = coverage / np.sum(coverage)
    if verbose:
        print('Normalized coverage sum: {}'.format(np.sum(covnorm)))

    # Time per pixel
    Tpix = np.zeros_like(covnorm)
    Tpix[thepix] = Ttot * covnorm[thepix]
    if verbose:
        print('Sum Tpix: {} s  ; Ttot = {} s'.format(np.sum(Tpix), Ttot))

    # RMS per pixel
    Sigpix = np.zeros_like(covnorm)
    Sigpix[thepix] = sigma_sec / np.sqrt(Tpix[thepix])
    if verbose:
        print('Total noise (with no averages in pixels): {}'.format(np.sum((Sigpix * Tpix) ** 2)))
    return Sigpix

def give_me_nus(nu, largeur, Nf):
    largeurq=largeur/Nf
    min=nu-largeur
    max=nu+largeur
    arr = np.linspace(min, max, Nf+1)
    mean_nu = np.zeros(Nf)

    for i in range(len(arr)-1):
        mean_nu[i]=np.mean(np.array([arr[i], arr[i+1]]))

    return mean_nu

def smoothing(maps, FWHMdeg, Nf, central_nus, verbose=True):
        """Convolve the maps to the FWHM at each sub-frequency or to a common beam if FWHMdeg is given."""
        fwhms = np.zeros(Nf)
        if FWHMdeg is not None:
            fwhms += FWHMdeg
        for i in range(Nf):
            if fwhms[i] != 0:
                maps[i, :, :] = hp.sphtfunc.smoothing(maps[i, :, :].T, fwhm=np.deg2rad(fwhms[i]),
                                                      verbose=verbose).T
        return fwhms, maps

def integrated(central_nus, bandwidth):
    min_nu = central_nus * (1 - 0.5 * bandwidth)
    max_nu = central_nus * (1 + 0.5 * bandwidth)
    nus_reconstructed = np.linspace(min_nu, max_nu, 4)

    return min_nu, max_nu, nus_reconstructed

def random_string(nchars):
    lst = [rd.choice(string.ascii_letters + string.digits) for n in range(nchars)]
    str = "".join(lst)
    return (str)

def get_multiple_nus(nu, bw, nf):
    nus=np.zeros(nf)
    edge=np.linspace(nu-(bw/2), nu+(bw/2), nf+1)
    for i in range(len(edge)-1):
        #print(i, i+1)
        nus[i]=np.mean([edge[i], edge[i+1]])
    return nus

def give_me_nu_fwhm_S4_2_qubic(nu, largeur, Nf, fwhmS4):

    def give_me_fwhm(nu, nuS4, fwhmS4):
        return fwhmS4*nuS4/nu

    largeurq=largeur/Nf
    min=nu*(1-largeur/2)
    max=nu*(1+largeur/2)
    arr = np.linspace(min, max, Nf+1)
    mean_nu = get_multiple_nus(nu, largeur, Nf)

    fwhm = give_me_fwhm(mean_nu, nu, fwhmS4)

    return mean_nu, fwhm

def compute_freq(band, Nfreq=None, relative_bandwidth=2.5):
    """
    Prepare frequency bands parameters
    band -- int,
        QUBIC frequency band, in GHz.
        Typical values: 150, 220
    relative_bandwidth -- float, optional
        Ratio of the difference between the edges of the
        frequency band over the average frequency of the band:
        2 * (nu_max - nu_min) / (nu_max + nu_min)
        Typical value: 0.25
    Nfreq -- int, optional
        Number of frequencies within the wide band.
        If not specified, then Nfreq = 15 if band == 150
        and Nfreq = 20 if band = 220
    """

    if Nfreq is None:
        Nfreq = {150: 15, 220: 20}[band]

    nu_min = band * (1 - relative_bandwidth / 2)
    nu_max = band * (1 + relative_bandwidth / 2)

    Nfreq_edges = Nfreq + 1
    base = (nu_max / nu_min) ** (1. / Nfreq)

    nus_edge = nu_min * np.logspace(0, Nfreq, Nfreq_edges, endpoint=True, base=base)
    nus = np.array([(nus_edge[i] + nus_edge[i - 1]) / 2 for i in range(1, Nfreq_edges)])
    deltas = np.array([(nus_edge[i] - nus_edge[i - 1]) for i in range(1, Nfreq_edges)])
    Delta = nu_max - nu_min
    Nbbands = len(nus)
    return Nfreq_edges, nus_edge, nus, deltas, Delta, Nbbands

def nus_for_iib(nu, bw):
    min=nu-(bw/2)
    max=nu+(bw/2)
    #print(min, max)
    nus = np.linspace(min, max, 4)
    return nus

def nus_for_iib(nu, bw):
    min=nu-(bw/2)
    max=nu+(bw/2)
    #print(min, max)
    nus = np.linspace(min, max, 4)
    return nus

def get_dust_convolved(model, nu, fwhm, modified=True, beta0=1.54, beta1=1.54, nb=100, verbose=True):

    def scaling_factor(maps, nus, analytic_expr, beta0, beta1, nubreak):
        nb_nus = maps.shape[0]
        newmaps = np.zeros(maps.shape)
        #print(sed1b)
        for i in range(nb_nus):
            _, sed1b = sed(analytic_expr, nus[i], beta1, beta1, nu0=nus[i], nubreak=nubreak)
            _, sed2b = sed(analytic_expr, nus[i], beta0, beta1, nu0=nus[i], nubreak=nubreak)
            print('nu is {} & Scaling factor is {:.8f}'.format(nus[i], sed2b))
            newmaps[i] = maps[i] * sed2b
        return newmaps, sed1b, sed2b


    def sed(analytic_expr, nus, beta0, beta1, temp=20, hok=constants.h * 1e9 / constants.k, nubreak=200, nu0=200):
        sed_expr = AnalyticComponent(analytic_expr,
                             nu0=nu0,
                             beta_d0=beta0,
                             beta_d1=beta1,
                             temp=temp,
                             nubreak=nubreak,
                             h_over_k = hok)
        return nus, sed_expr.eval(nus)



    sky = pysm3.Sky(nside=256, preset_strings=[model])
    dust_maps = np.zeros(((len(nu), 3, 12*256**2)))
    for indi, i in enumerate(nu) :
        dust_maps[indi] = sky.get_emission(i*u.GHz, None)*utils.bandpass_unit_conversion(i*u.GHz,None, u.uK_CMB)
        if verbose:
            print('Convolved to {:.2f} deg'.format(fwhm[indi]))
        dust_maps[indi] = hp.sphtfunc.smoothing(dust_maps[indi, :, :], fwhm=np.deg2rad(fwhm[indi]),verbose=False)

    if modified:
        #print('y')
        dust_maps, _, _ = scaling_factor(dust_maps, nu, s4bi.double_beta_dust_FGB_Model(), beta0, beta1, nubreak=nb)
    return dust_maps

def scaling_factor(maps, nus, analytic_expr, beta0, beta1, nubreak):
    nb_nus = maps.shape[0]
    newmaps = np.zeros(maps.shape)
    #print(sed1b)
    for i in range(nb_nus):
        _, sed1b = sed(analytic_expr, nus[i], beta1, beta1, nu0=nus[i], nubreak=nubreak)
        _, sed2b = sed(analytic_expr, nus[i], beta0, beta1, nu0=nus[i], nubreak=nubreak)
        print('nu is {} & Scaling factor is {:.8f}'.format(nus[i], sed2b))
        newmaps[i] = maps[i] * sed2b
    return newmaps, sed1b, sed2b

def sed(analytic_expr, nus, beta0, beta1, temp=20, hok=constants.h * 1e9 / constants.k, nubreak=200, nu0=200):
    sed_expr = AnalyticComponent(analytic_expr,
                             nu0=nu0,
                             beta_d0=beta0,
                             beta_d1=beta1,
                             temp=temp,
                             nubreak=nubreak,
                             h_over_k = hok)
    return nus, sed_expr.eval(nus)

class BImaps(object):

    def __init__(self, skyconfig, dict):
        self.dict = dict
        self.skyconfig = skyconfig
        self.nus = self.dict['frequency']
        self.bw = self.dict['bandwidth']
        self.fwhm = self.dict['fwhm']
        self.depth_i = self.dict['depth_i']
        self.depth_p = self.dict['depth_p']
        #self.depth_p_reconstructed = np.ones(self.Nf)*self.depth_i*np.sqrt(self.Nf)
        #self.depth_i_reconstructed = np.ones(self.Nf)*self.depth_p*np.sqrt(self.Nf)
        self.fwhmdeg = self.fwhm/60
        self.fsky = self.dict['fsky']
        self.edges = self.dict['edges']

        self.nside=256
        self.npix = 12*self.nside**2
        self.lmax=3 * self.nside
        ell, totDL, unlensedCL = qc.get_camb_Dl(lmax=self.lmax)
        mycls = qc.Dl2Cl_without_monopole(ell, totDL)
        mymaps = hp.synfast(mycls.T, self.nside, verbose=False, new=True)
        self.input_cmb_maps = mymaps
        self.input_cmb_spectra = totDL
        for k in skyconfig.keys():
            if k == 'cmb':
                self.seed = self.skyconfig['cmb']

    def get_cmb(self):
        np.random.seed(self.seed)
        ell, totDL, unlensedCL = qc.get_camb_Dl(lmax=2*self.nside+1)
        mycls = qc.Dl2Cl_without_monopole(ell, totDL)
        maps = hp.synfast(mycls.T, self.nside, verbose=False, new=True)
        return maps

    def get_sky(self):
        setting = []
        iscmb=False
        for k in self.skyconfig:
            if k == 'cmb' :
                iscmb=True
                maps = self.get_cmb()

                rndstr = random_string(10)
                hp.write_map('/tmp/' + rndstr, maps)
                cmbmap = pysm3.CMBMap(self.nside, map_IQU='/tmp/' + rndstr)
                os.remove('/tmp/' + rndstr)
                #setting.append(skyconfig[k])
            elif k=='dust':
                pass
            else:
                setting.append(self.skyconfig[k])

        sky = pysm3.Sky(nside=self.nside, preset_strings=setting)
        if iscmb:
            sky.add_component(cmbmap)

        return sky

    def getskymaps(self, same_resol=None, verbose=False, coverage=None, iib=False, noise=False, signoise=1., beta=[]):

        """

        """

        sky=self.get_sky()
        allmaps = np.zeros(((len(self.nus), 3, self.npix)))
        if same_resol is not None:
            self.fwhmdeg = np.ones(len(self.nus))*np.max(same_resol)

        if verbose:
            print("    FWHM : {} deg \n    nus : {} GHz \n    Bandwidth : {} GHz\n\n".format(self.fwhmdeg, self.nus, self.bw))

        if iib:
            def get_nus_for_iib(edge_min, edge_max):
                min = edge_min
                max = edge_max
                nus = np.linspace(min, max, 4)
                return nus

            for indi, i in enumerate(self.nus[:-1]):

                nus_edges = get_nus_for_iib(self.edges[indi][0], self.edges[indi][1])
                #print(self.edges)
                print(nus_edges)
                #print()
                #print(get_nus_for_iib(self.edges[indi], self.edges[indi+1]))
                #print()
                maps_edges=np.zeros(((4, 3, self.npix)))
                if verbose:
                    print("Integrated from {:.2f} to {:.2f} GHz".format(nus_edges[0], nus_edges[-1]))
                for indj, j in enumerate(nus_edges):
                    maps_edges[indj] = sky.get_emission(j*u.GHz, np.ones(4))*utils.bandpass_unit_conversion(j*u.GHz,np.ones(4), u.uK_CMB)
                    if verbose and indj == 1:
                        print('Reconvolution to {:.2f} deg'.format(self.fwhmdeg[indi]))
                    maps_edges[indj] = hp.sphtfunc.smoothing(maps_edges[indj, :, :], fwhm=np.deg2rad(self.fwhmdeg[indi]),verbose=False)

                allmaps[indi] = np.mean(maps_edges, axis=0)
        else:
            allmaps=np.zeros(((len(self.nus), 3, self.npix)))
            for i in self.skyconfig.keys():
                if i == 'cmb':
                    cmbmap = self.get_cmb()
                    for j in range(len(self.nus)):
                        allmaps[j]+=cmbmap
                elif i == 'dust':
                    if self.skyconfig[i] == 'd0':
                        if verbose:
                            print('Model : d0 -> Spectral index beta is constant on the sky (set to 1.54)')
                        #dustmaps = get_dust_convolved('d0', self.nus, self.fwhmdeg, modified=False, verbose=verbose)
                        #allmaps+=dustmaps
                    elif self.skyconfig[i] == 'd02b':
                        print('> Modified Dust')
                        if verbose:
                            print('Model : d02b -> Twos spectral index beta with nu_break')

                        #add Elenia's definition
                        dustmaps=get_scaled_dust_dbmmb_map(nu_ref=beta[3], nu_vec=self.nus, beta0=beta[0], beta1=beta[1], nubreak=beta[2], nside=self.nside, fsky=1, radec_center=[0., -57.], temp=20.)
                        #dustmaps = get_dust_convolved('d0', self.nus, self.fwhmdeg, modified=True, beta0=beta[0], beta1=beta[1], nb=beta[2], verbose=verbose)
                        allmaps+=dustmaps
                    else:
                        print('No dust')

                elif i == 'synchrotron':
                    print('> Synchrotron')
                    sky_sync = pysm3.Sky(nside=self.nside, preset_strings=['s0'])
                    sync_maps = np.zeros(((len(self.nus), 3, 12*self.nside**2)))
                    for indi, i in enumerate(self.nus):
                        sync_maps[indi] = sky_sync.get_emission(i*u.GHz, None)*utils.bandpass_unit_conversion(i*u.GHz,None, u.uK_CMB)
                        allmaps[indi]+=sync_maps[indi]

                else:
                    pass

        #hp.mollview(allmaps[0, 1])

        for j in range(len(self.fwhmdeg)):
            allmaps[j] = hp.sphtfunc.smoothing(allmaps[j, :, :], fwhm=np.deg2rad(self.fwhmdeg[j]),verbose=False)




        def create_noisemaps(signoise):
            np.random.seed(None)
            N = np.zeros(((len(self.nus), 3, self.npix)))
            for ind_nu, nu in enumerate(self.nus):

                sig_i=signoise*self.depth_i[ind_nu]/(np.sqrt(hp.nside2pixarea(self.nside, degrees=True)) * 60)
                N[ind_nu, 0] = np.random.normal(0, sig_i, 12*self.nside**2)

                sig_p=signoise*self.depth_p[ind_nu]/(np.sqrt(hp.nside2pixarea(self.nside, degrees=True)) * 60)
                N[ind_nu, 1] = np.random.normal(0, sig_p, 12*self.nside**2)*np.sqrt(2)
                N[ind_nu, 2] = np.random.normal(0, sig_p, 12*self.nside**2)*np.sqrt(2)

            return N

        if noise:
            noisemaps = create_noisemaps(signoise)
            maps_noisy = allmaps+noisemaps

            if coverage is not None:
                thr = 0.1
                mymask = (coverage > (np.max(coverage)*thr)).astype(int)
                pixok = mymask > 0
                maps_noisy[:, :, ~pixok] = hp.UNSEEN
                noisemaps[:, :, ~pixok] = hp.UNSEEN
                allmaps[:, :, ~pixok] = hp.UNSEEN

            return maps_noisy, allmaps, noisemaps
