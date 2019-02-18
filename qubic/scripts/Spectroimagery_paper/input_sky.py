from __future__ import division
import healpy as hp
import numpy as np

import qubic

def scaling_dust(freq1, freq2, sp_index=1.59):
    '''
    Calculate scaling factor for dust contamination
    Frequencies are in GHz
    '''
    freq1 = float(freq1)
    freq2 = float(freq2)
    x1 = freq1 / 56.78
    x2 = freq2 / 56.78
    S1 = x1**2. * np.exp(x1) / (np.exp(x1) - 1)**2.
    S2 = x2**2. * np.exp(x2) / (np.exp(x2) - 1)**2.
    vd = 375.06 / 18. * 19.6
    scaling_factor_dust = (np.exp(freq1 / vd) - 1) / \
                          (np.exp(freq2 / vd) - 1) * \
                          (freq2 / freq1)**(sp_index + 1)
    scaling_factor_termo = S1 / S2 * scaling_factor_dust
    return scaling_factor_termo


def dust_spectra(ll, nu):
    fact = (ll * (ll + 1)) / (2 * np.pi)
    coef = 1.39e-2
    spectra_dust = [np.zeros(len(ll)),
                  coef * (ll / 80.)**(-0.42) / (fact * 0.52),
                  coef * (ll / 80.)**(-0.42) / fact,
                  np.zeros(len(ll))]
    sc_dust = scaling_dust(150, nu)
    return fact * sc_dust * spectra_dust


def cmb_plus_dust(cmb, dust, Nbsubbands, sub_nus, kind='IQU'):
    '''
    Sum up clean CMB map with dust using proper scaling coefficients
    '''
    Nbpixels = cmb.shape[0]
    nstokes = len(kind)  # Number of stokes parameters used in the simu
    x0 = np.zeros((Nbsubbands, Nbpixels, 3))
    # Let's fill the maps:
    for i in range(Nbsubbands):
        for istokes in xrange(nstokes):
            if kind == 'QU':  # This condition keeps the order IQU in the healpix map
                x0[i, :, istokes + 1] = cmb.T[istokes + 1] + dust.T[istokes + 1] * scaling_dust(150, sub_nus[i], 1.59)
            else:
                x0[i, :, istokes] = cmb.T[istokes] + dust.T[istokes] * scaling_dust(150, sub_nus[i], 1.59)
    return x0


def create_input_sky(d, skypars):
    Nf = int(d['nf_sub'])
    band = d['filter_nu'] / 1e9
    filter_relative_bandwidth = d['filter_relative_bandwidth']
    _, _, nus_in, _, _, Nbbands_in = qubic.compute_freq(band, filter_relative_bandwidth, Nf)
    # seed
    if d['seed']:
        np.random.seed(d['seed'])
        # Generate the input CMB map
        sp = qubic.read_spectra(skypars['r'])
        cmb = np.array(hp.synfast(sp, d['nside'], new=True, pixwin=True, verbose=False)).T
        # Generate the dust map
        coef = skypars['dust_coeff']
        ell = np.arange(1, 3 * d['nside'])
        fact = (ell * (ell + 1)) / (2 * np.pi)
        spectra_dust = [np.zeros(len(ell)),
                        coef * (ell / 80.) ** (-0.42) / (fact * 0.52),
                        coef * (ell / 80.) ** (-0.42) / fact,
                        np.zeros(len(ell))]
        dust = np.array(hp.synfast(spectra_dust, d['nside'], new=True, pixwin=True, verbose=False)).T

        # Combine CMB and dust. As output we have N 3-component maps of sky.
        x0 = cmb_plus_dust(cmb, dust, Nbbands_in, nus_in, d['kind'])
        return x0
