import healpy as hp
import numpy as np
import os
import random as rd
import string
from importlib import reload
from pylab import *
from scipy import constants

import pysm3
import pysm3.units as u
from pysm3 import utils
#import qubicplus
import qubic
from qubic import camb_interface as qc
from qubic import NamasterLib as nam

from fgbuster.component_model import (CMB, Dust, Dust_2b, Synchrotron, AnalyticComponent)
import fgbuster
import warnings
warnings.filterwarnings("ignore")
from builtins import any
#############################################################################
# This library contains all things for
# - define qubicplus configuration
# - component separation with bandpass integration
# ###########################################################################

#UNITS CONVERSION ~~~~~~~~~~~~~~~~
def _rj2cmb(freqs):
    return (np.ones_like(freqs) * u.K_RJ).to(
        u.K_CMB, equivalencies=u.cmb_equivalencies(freqs * u.GHz)).value


def _cmb2rj(freqs):
    return (np.ones_like(freqs) * u.K_CMB).to(
        u.K_RJ, equivalencies=u.cmb_equivalencies(freqs * u.GHz)).value

def _rj2jysr(freqs):
    return (np.ones_like(freqs) * u.K_RJ).to(
        u.Jy / u.sr, equivalencies=u.cmb_equivalencies(freqs * u.GHz)).value


def _jysr2rj(freqs):
    return (np.ones_like(freqs) * u.Jy / u.sr).to(
        u.K_RJ, equivalencies=u.cmb_equivalencies(freqs * u.GHz)).value


def _cmb2jysr(freqs):
    return (np.ones_like(freqs) * u.K_CMB).to(
        u.Jy / u.sr, equivalencies=u.cmb_equivalencies(freqs * u.GHz)).value


def _jysr2cmb(freqs):
    return (np.ones_like(freqs) * u.Jy / u.sr).to(
        u.K_CMB, equivalencies=u.cmb_equivalencies(freqs * u.GHz)).value

# GENERAL FUNCTIONS AND QUBICPLUS RELATED STUFF ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def get_coverage(fsky, nside, center_radec=[0., -57.]):
    center = qubic.equ2gal(center_radec[0], center_radec[1])
    uvcenter = np.array(hp.ang2vec(center[0], center[1], lonlat=True))
    uvpix = np.array(hp.pix2vec(nside, np.arange(12*nside**2)))
    ang = np.arccos(np.dot(uvcenter, uvpix))
    indices = np.argsort(ang)
    okpix = ang < -1
    okpix[indices[0:int(fsky * 12*nside**2)]] = True
    mask = np.zeros(12*nside**2)
    mask[okpix] = 1
    return mask


def get_edges(nus, bandwidth):
    edges=np.zeros((len(nus), 2))
    dnu_nu=bandwidth/nus
    edges_max=nus * (1. + dnu_nu/2)
    edges_min=nus * (1. - dnu_nu/2)
    for i in range(len(nus)):
        edges[i, 0]=edges_min[i]
        edges[i, 1]=edges_max[i]
    return edges


#take into account BI sup-opt (noise freq. correlations) at any given frequency
def fct_subopt(nus, nsubs):
    '''
    This function evaluates QUBIC sub-optimality on r at a given input frequency using
    L.Mousset's work (QUBIC paper II)
    '''
    subnus = [150., 220]
    nsubs_vec = [2,3,4,5,7]
    subval = []
    subval.append([1.25,1.1]) #2
    subval.append([1.35,1.15]) #3
    subval.append([1.35, 1.1]) #4
    subval.append([1.4, 1.2]) #5
    subval.append([1.5, 1.4]) #7
    #subval.append([1.65,1.45]) #8
    fct_subopt = np.poly1d(np.polyfit(subnus, subval[nsubs_vec.index(nsubs)], 1))
    return fct_subopt(nus)

#create a BI version of another experiment, eg. CMB-s4 (config=s4_config)
def qubicify(config, qp_nsubs, qp_effective_fraction, include_sub_opt = True):
    '''
    This function generates a BI version of a given instrumental configuration (generally S4)
    by specifying the number of sub-bands in each physical band.
    The user can specify if the sub-opt. on r has to be included or not
    '''
    #total number of bands
    nbands = np.sum(qp_nsubs)
    #copy the keys from the input instrumental dictionary and then reset them to empty lists
    qp_config = config.copy()
    for k in qp_config.keys():
        qp_config[k]=[]
        
    qp_config['name'] = 'BI{}'.format(np.max(qp_nsubs)) #e.g. name = 'BI3' if there are 3 subbands in each S4 band
    qp_config['center_radec'] = config['center_radec']
    qp_config['nbands'] = nbands
    qp_config['fsky'] = config['fsky']
    qp_config['ntubes'] = config['ntubes']
    qp_config['nyears'] = config['nyears']
    qp_config['initial_band'] = []

    for i in range(len(config['frequency'])):
       #def sub-bands in each band
        newedges = np.linspace(config['edges'][i][0], config['edges'][i][-1], qp_nsubs[i]+1)
        newfreqs = (newedges[0:-1]+newedges[1:])/2
        newbandwidth = newedges[1:] - newedges[0:-1]
        newdnu_nu = newbandwidth / newfreqs
        #def new fhwm in each sub-band
        newfwhm = config['fwhm'][i] * config['frequency'][i]/newfreqs
        
        #def noise scaling factor
        scalefactor_noise = np.sqrt(qp_nsubs[i]) / qp_effective_fraction[i]
        #add sup-opt on r
        if qp_nsubs[i]>1:
            if include_sub_opt:
                scalefactor_noise *= fct_subopt(config['frequency'][i], np.max(qp_nsubs))
                
        #rescale noise
        newdepth_p = config['depth_p'][i] * np.ones(qp_nsubs[i]) * scalefactor_noise
        newdepth_i = config['depth_i'][i] * np.ones(qp_nsubs[i]) * scalefactor_noise
        newdepth_e = config['depth_e'][i] * np.ones(qp_nsubs[i]) * scalefactor_noise
        newdepth_b = config['depth_b'][i] * np.ones(qp_nsubs[i]) * scalefactor_noise
        newell_min = np.ones(qp_nsubs[i]) * config['ell_min'][i]
        newnside = np.ones(qp_nsubs[i]) * config['nside'][i]
        neweffective_fraction = np.ones(qp_nsubs[i]) * qp_effective_fraction[i]
        initial_band = np.ones(qp_nsubs[i]) * config['frequency'][i]

        for k in range(qp_nsubs[i]):
            if qp_effective_fraction[i] != 0:
                qp_config['frequency'].append(newfreqs[k])
                qp_config['depth_p'].append(newdepth_p[k])
                qp_config['depth_i'].append(newdepth_i[k])
                qp_config['depth_e'].append(newdepth_e[k])
                qp_config['depth_b'].append(newdepth_b[k])
                qp_config['fwhm'].append(newfwhm[k])
                qp_config['bandwidth'].append(newbandwidth[k])
                qp_config['dnu_nu'].append(newdnu_nu[k])
                qp_config['ell_min'].append(newell_min[k])
                qp_config['nside'].append(newnside[k])

                qp_config['effective_fraction'].append(neweffective_fraction[k])
                qp_config['initial_band'].append(initial_band[k])
        edges=get_edges(np.array(qp_config['frequency']), np.array(qp_config['bandwidth']))
        qp_config['edges']=edges.copy()
        #for k in range(qp_nsubs[i]+1):
        #    if qp_effective_fraction[i] != 0:
        #        qp_config['edges'].append(newedges[k])
        
    #convert all the keys from list to np array    
    fields = ['frequency', 'depth_p', 'depth_i', 'depth_e', 'depth_b', 'fwhm', 'bandwidth',
              'dnu_nu', 'ell_min', 'nside', 'edges', 'effective_fraction', 'initial_band']
    for j in range(len(fields)):
        qp_config[fields[j]] = np.array(qp_config[fields[j]])

    return qp_config


def plot_s4_bi_config_sensitivity(s4_config, qp_config):
    #check sensitivities and freq. bands
    s4_freq = s4_config['frequency']
    bi_freq = qp_config['frequency']
    
    figure(figsize=(16, 12))
    subplot(2, 2, 1)
    title('Depth I')
    errorbar(s4_freq, s4_config['depth_i'], xerr = s4_config['bandwidth']/2, fmt='ro', label='S4')
    errorbar(bi_freq, qp_config['depth_i'], xerr = qp_config['bandwidth']/2, fmt='bo', label='BI')
    xlabel('Freq. [GHz]')
    ylabel(r'Depth [$\mu K \times$arcmin]')
    legend(loc='best')

    subplot(2, 2, 2)
    title('Depth P')
    errorbar(s4_freq, s4_config['depth_p'] ,xerr = s4_config['bandwidth']/2, fmt='ro', label='S4')
    errorbar(bi_freq, qp_config['depth_p'], xerr = qp_config['bandwidth']/2, fmt='bo', label='BI')
    xlabel('Freq. [GHz]')
    ylabel(r'Depth [$\mu K \times$arcmin]')
    legend(loc='best')
    
    subplot(2, 2, 3)
    title('FWHM')
    errorbar(s4_freq, s4_config['fwhm'] ,xerr = s4_config['bandwidth']/2, fmt='ro', label='S4')
    errorbar(bi_freq, qp_config['fwhm'], xerr = qp_config['bandwidth']/2, fmt='bo', label='BI')
    xlabel('Freq. [GHz]')
    ylabel('FWHM [arcmin]')
    legend(loc='best')
    
    savefig('./Instrumental_performance_comparison.png')
    return

def check_s4_bi_noise_proportion(s4_config, qp_config):
    #check proportion btw S4 and BI sensitivity level

    #for each band take 1. depth of S4 central freq, 2. depth of BI at the same freq 3.sub-opt factor at that freq
    #4. check that BI sens is sqrt(5)*sub_opt wrt S4 sens

    #take only freq above 50 GHz
    freq_set = s4_config['frequency'][3:]
    print('In this sub-set of frequencies: ', freq_set)
    #sub-opt factor at s4 freq
    sub_opt_values = [fct_subopt(freq_val) for freq_val in freq_set]

    #s4_depts i and p
    s4_dep_i = s4_config['depth_i'][3:]
    s4_dep_p = s4_config['depth_p'][3:]

    #select subset of BI sens, by taking only sens at freq=S4_freqs

    ind_vec = []
    for freq_val in freq_set:
        indx = np.where(np.round(qp_config['frequency'][3:],3)==np.round(freq_val,3))[0][0]
        ind_vec.append(indx)
    
    
    bi_dep_i = [ np.round(qp_config['depth_i'][3:][i],3) for i in ind_vec ]
    bi_dep_p = [ np.round(qp_config['depth_p'][3:][i],3) for i in ind_vec ]

    expected_bi_dep_i = np.round(s4_dep_i*np.sqrt(5)*sub_opt_values, 3)
    expected_bi_dep_p = np.round(s4_dep_p*np.sqrt(5)*sub_opt_values, 3)

    #print if the BI sensitivities are correctly rescaled or not
    if ((bi_dep_i==expected_bi_dep_i).all()==True and (bi_dep_p==expected_bi_dep_p).all()==True):
        print('The BI sensitivities are correctly rescaled in I and P')
    else:
        print('ERROR: The BI sensitivities are uncorrectly rescaled in I and/or P. Check you code!')
        return
    
# COMPSEP RELATED FUNCTIONS ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def get_maps_for_namaster_QU(cmb_map_QU, npix):
    '''
    This function take cmb map with shape (QU, npix) and return cmb map with shape (IQU x npix) where
    I component is zero. To be used when you apply comp sep over QU only.
    '''
    cmb_map_IQU=np.zeros((3, npix))
    cmb_map_IQU[1:]=cmb_map_QU.copy()
    return cmb_map_IQU


def get_comp_for_fgb(nu0, model, fix_temp, bw=1., x0=[], fixsync=True):
    '''
    This function returns a list 'comp' containing the fgb components
    to be passed as input of the component separation function
    INPUT: ref. freq, dust_model, fix_temp=None if T_d is fixed,
    break_steepness for the 2-beta dust model, initial guess x0, fixsync=True if the synchrotron has no parameter
    '''
    comp=[fgbuster.component_model.CMB()]
    if model == '1b':
        if fix_temp is not None :
            comp.append(fgbuster.component_model.Dust(nu0=nu0, temp=fix_temp))
            comp[1].defaults=x0
        else:
            comp.append(fgbuster.component_model.Dust(nu0=nu0))
            comp[1].defaults=x0
    elif model == '2b':
        if fix_temp is not None :
            comp.append(fgbuster.component_model.Dust_2b(nu0=nu0, temp=fix_temp, break_width=bw))
            comp[1].defaults=x0
        else:
            comp.append(fgbuster.component_model.Dust_2b(nu0=nu0, break_width=bw))
            comp[1].defaults=x0
    else:
        raise TypeError('Not the good model')

    if fixsync:
        comp.append(fgbuster.component_model.Synchrotron(nu0=nu0, beta_pl=-3))
    else:
        comp.append(fgbuster.component_model.Synchrotron(nu0=nu0))
        comp[2].defaults=[-3]

    return comp


def get_comp_from_MixingMatrix(r, comp, instr, data, frequency, covmap, noise, nside):
    """
    This function estimate components from MixingMatrix of fgbuster with estimated parameters
    """
    pixok=covmap>0

    # Define Mixing Matrix from FGB
    A=fgbuster.mixingmatrix.MixingMatrix(*comp)
    A_ev=A.evaluator(np.array(frequency))
    A_maxL=A_ev(np.array(r.x))

    if noise:
        invN = np.diag(hp.nside2resol(nside, arcmin=True) / (instr.depth_p))**2
        maps_separe=fgbuster.algebra.Wd(A_maxL, data.T, invN=invN).T
    else:
        maps_separe=fgbuster.algebra.Wd(A_maxL, data.T).T

    maps_separe[:, :, ~pixok]=hp.UNSEEN

    return maps_separe


def get_good_config(config, prop):
    '''
    This function defines and returns the: frequency, depths, fwhm
    of the instrument used in the FGB component separation.
    The instrument can be: a full S4 configuration, full S4-BI configuration or an hybrid configuration
    '''
    config1=config[0]
    config2=config[1]
    nus=np.array(list(config1['frequency'])+list(config2['frequency']))
    depth1_i=config1['depth_i']/(np.sqrt(prop[0]))
    depth1_p=config1['depth_p']/(np.sqrt(prop[0]))
    depth2_i=config2['depth_i']/(np.sqrt(prop[1]))
    depth2_p=config2['depth_p']/(np.sqrt(prop[1]))

    depth_i=np.array(list(depth1_i)+list(depth2_i))
    depth_p=np.array(list(depth1_p)+list(depth2_p))
    fwhm=np.zeros(42)

    if prop[0] == 1 :
        depth_i=config1['depth_i']
        depth_p=config1['depth_p']
        nus=config1['frequency']
        fwhm=np.zeros(9)
    elif prop[1] == 1:
        depth_i=config2['depth_i']
        depth_p=config2['depth_p']
        nus=config2['frequency']
        fwhm=np.zeros(33)
    else:
        pass

    return nus, depth_i, depth_p, fwhm


def get_cov_for_weighted(n_freq, depths_i, depths_p, coverage, nside=256):
    '''
    This function is used in case of "weighted_comp_sep" with FGB
    '''
    npix=12*nside**2
    ind=coverage > 0

    noise_cov = np.ones(((n_freq, 2, npix)))
    #noise_cov = np.ones(((n_freq, 3, npix)))

    for i in range(n_freq):
        noise_cov[i, 0] = np.ones(npix)*depths_p[i]**2
        noise_cov[i, 1] = np.ones(npix)*depths_p[i]**2
        #noise_cov[i, 0] = np.ones(npix)*depths_i[i]**2
        #noise_cov[i, 1] = np.ones(npix)*depths_p[i]**2
        #noise_cov[i, 2] = np.ones(npix)*depths_p[i]**2

    noise_cov[:, :, ~ind]=hp.UNSEEN

    return noise_cov


def get_instr(config, instr_name, N_SAMPLE_BAND):

    freq_maps=config['frequency']

    print('###################')
    print('Instrument is: {}'.format(instr_name))
    print('Number of samples for bandpass integration: {}'.format(N_SAMPLE_BAND))
    print('###################')
    instrument = fgbuster.observation_helpers.get_instrument(instr_name)

    bandpasses = config['bandwidth']

    freq_maps_bp_integrated = np.zeros_like(freq_maps)
    new_list_of_freqs = []

    for f in range(freq_maps_bp_integrated.shape[0]):

        fmin = freq_maps[f]-bandpasses[f]/2
        fmax = freq_maps[f]+bandpasses[f]/2
        freqs = np.linspace(fmin, fmax, N_SAMPLE_BAND)
        weights_flat = np.ones(N_SAMPLE_BAND)
        weights = weights_flat.copy()/ _jysr2rj(freqs)
        weights /= _rj2cmb(freqs)
        weights /= np.trapz(weights, freqs * 1e9)
        new_list_of_freqs.append((freqs, weights))

    instrument.frequency = new_list_of_freqs

    return instrument


def ParamCompSep(config, prop, nside, skyconfig, model, foreg_maps, coverage, iib, noise=True, fix_temp=None,
                 x0=[], break_width=1., fixsync=True, nu0=85, Nsample=100):

    covmap = coverage
    pixok = covmap>0

    if prop[0] == 1 : #s4
        conf=config[0]
        fgmaps = foreg_maps[0]
        print('Has fg_maps the same freq. length of the instrument? ', (len(conf['frequency'])==fgmaps.shape[0]))
        inputs, inputs_noiseless, _ = qubicplus_skygen_lib.BImaps(skyconfig, conf, nside=nside).getskymaps(fg_maps=fgmaps,
                                      same_resol=0,
                                      verbose=True,
                                      coverage=covmap,
                                      noise=True)
    elif prop[1] == 1: #bi
        conf=config[1]
        fgmaps = foreg_maps[1]
        print('Has fg_maps the same freq. length of the instrument? ', (len(conf['frequency'])==fgmaps.shape[0]))
        inputs, inputs_noiseless, _ = qubicplus_skygen_lib.BImaps(skyconfig, conf, nside=nside).getskymaps(fg_maps=fgmaps,
                                      same_resol=0,
                                      verbose=True,
                                      coverage=covmap,
                                      noise=True)

    ###### Preparation for COMPSEP ######
    nus, depth_i, depth_p, fwhm = utilitylib.get_good_config(config, prop)

    if len(nus) == 9:
        name='CMBS4'
        n_freq=9
    elif len(nus)==33:
        name='QubicPlus'
        n_freq=33
    else:
        name='CMBS4BI'
        n_freq=42

    print()
    print('Define instrument taking into account bandpass integration')
    #def instrument and instrument.frequency taking bandpass integration into account
    if iib==1:
        instr = fgbuster.get_instrument(name)
        instr.frequency=nus
        print('###################')
        print('Instrument is: {}'.format(name))
        print('Number of samples for bandpass integration: {}'.format(iib))
        print('###################')
    elif iib>1:
        instr = get_instr(conf, Nsample)
    else:
        print('ERROR: Set correct number of freq. for bandpass integration! At least 1')

    #set depths and fwhm equal to the corresponding configuration
    instr.depth_i=depth_i
    instr.depth_p=depth_p
    instr.fwhm=fwhm

    print()
    print('Define components')
    comp = utilitylib.get_comp_for_fgb(nu0=nu0, model=model, fix_temp=fix_temp, x0=x0, bw=break_width, fixsync=fixsync)

    print()
    print('##### COMP SEP #####')

    options={'maxiter': 100000}
    #tol=1e-18
    
    #apply compsep only on the Q,U maps
    data = inputs[:, 1:, pixok] #take only pixok to speed up the code

    #cov=utilitylib.get_cov_for_weighted(len(nus), depth_i, depth_p, covmap, nside=nside)

    r=fgbuster.basic_comp_sep(comp, instr, data, options=options, tol=1e-18, method='TNC')#, bounds=bnds)
    #r=fgbuster.weighted_comp_sep(comp, instr, data, cov, options=options, tol=1e-18, method='TNC')

    print('\nMessage -> ', r.message)
    print('# of function evaluation -> ', r.nfev)
    print()

    print('...compsep done! \n')
    print('Estimated params: ', r.x)
    print('Estimated errors: ', np.diagonal(r.Sigma))

    components = get_comp_from_MixingMatrix(r, comp, instr, inputs[:, 1:, :], nus, covmap, noise, nside)
    components_noiseless = get_comp_from_MixingMatrix(r, comp, instr, inputs_noiseless[:, 1:, :], nus, covmap, False, nside)
    return components, components_noiseless, r

def configure_fgb_instrument(conf, Nsample, Add_Planck=False):
    '''
    This function defines the instrument for FGB compsep by assigning frequency, depths, fwhm
    -Input: instrum. configuration dictionary and N_SAMPLE_BAND
    '''
    nus = conf['frequency'] #instrument freqs
    
    #Case: w/o additional Planck data
    if Add_Planck == False:
        #set experiment name to be one of the experiments in the cmbdb experiment file
        if len(nus) == 9:
            name='CMBS4'
        elif ((len(nus)-3) % 6) == 0: #e.g. if n_subbands=5, then len(nus)==33
            n_subs = int((len(nus)-3)/6)
            print(n_subs)
            name='QubicPlus_{}subbands'.format(n_subs)
            print(name)
        else:
            name='CMBS4BI'
        print()
        print('Define instrument taking into account bandpass integration')
        #def instrument and instrument.frequency taking bandpass integration into account
        if Nsample==1:
            instr = fgbuster.observation_helpers.get_instrument(name)
            #set depth manually to make sure it's the same level as the simulated instrument
            instr.depth_i = conf['depth_i']
            instr.depth_p = conf['depth_p']*np.sqrt(2) #take this as depth_q and depth_u, not actual depth_p
            print('###################')
            print('Instrument is: {}'.format(name))
            print('Number of samples for bandpass integration: {}'.format(Nsample))
            print('###################')
        elif Nsample>1:
            instr = get_instr(conf, name, Nsample)
            #set depth manually to make sure it's the same level as the simulated instrument
            instr.depth_i = conf['depth_i']
            instr.depth_p = conf['depth_p']*np.sqrt(2)
        else:
            print('ERROR: Set correct number of freq. for bandpass integration! At least 1')
    
    #Case: with additional Planck data        
    elif Add_Planck == True:
        #set experiment name as S4 or BI + Planck
        if len(nus) == 9:
            name='CMBS4_plus_Planck'
        elif ((len(nus)-3) % 6) == 0: #e.g. if n_subbands=5, then len(nus)==33
            n_subs = int((len(nus)-3)/6)
            print(n_subs)
            name='QubicPlus_{}subbands_plus_Planck'.format(n_subs)
            print(name)
        else:
            name='CMBS4BI'
        print()
        print('Define instrument taking into account bandpass integration')
        #def instrument and instrument.frequency taking bandpass integration into account
        if Nsample==1:
            instr = fgbuster.observation_helpers.get_instrument(name)
            #set depth manually to make sure it's the same level as the simulated instrument
            instr.depth_i[0:-1] = conf['depth_i']
            instr.depth_p[0:-1] = conf['depth_p']*np.sqrt(2) #take this as depth_q and depth_u, not actual depth_p
            #instr.depth_p[-1] = instr.depth_p[-1]*np.sqrt(2) #multiply Planck noise-per-pixel by sqrt(2) cause it's an half-mission
            print('###################')
            print('Instrument is: {}'.format(name))
            print('Number of samples for bandpass integration: {}'.format(Nsample))
            print('###################')
        elif Nsample>1:
            instr = get_instr(conf, name, Nsample)
            #set depth manually to make sure it's the same level as the simulated instrument
            instr.depth_i[0:-1] = conf['depth_i']
            instr.depth_p[0:-1] = conf['depth_p']*np.sqrt(2)
            #instr.depth_p[-1] = instr.depth_p[-1]*np.sqrt(2) #multiply Planck noise-per-pixel by sqrt(2) cause it's an half-mission
        else:
            print('ERROR: Set correct number of freq. for bandpass integration! At least 1')        
        
    print(instr.depth_p)
    return instr

def configure_fgb_component(skyconfig, nu0, temp_is_fixed):
    '''
    This function defines the component list for FGB compsep by sorting through the skyconfig dict
    '''
    comp = []
    #search for cmb
    if any('cmb' in comp for comp in skyconfig.keys()):
        print('Compsep on CMB')
        comp.append(fgbuster.component_model.CMB())
    #search for dust, synch, etc as pysm models
    if any('pysm_fg' in comp for comp in skyconfig.keys()):
        if any('d' in model for model in skyconfig['pysm_fg']):
            print('Compsep on Dust')
            if temp_is_fixed:
                comp.append(fgbuster.component_model.Dust(nu0=353., temp=20))
            else:
                comp.append(fgbuster.component_model.Dust(nu0=353.))
        if any('s' in model for model in skyconfig['pysm_fg']):
            print('Compsep on Synch')
            comp.append(fgbuster.component_model.Synchrotron(nu0=23.))
    if any('not_pysm_fg' in comp for comp in skyconfig.keys()):
            print('Compsep on Dust 2beta')
            comp.append(fgbuster.component_model.Dust_2b(nu0=nu0))
        
    return comp


def get_num_component(skyconfig):
    '''
    This function returns number of components in the sky dictionary
    '''
    n_comp = 0
    #search for cmb
    if any('cmb' in comp for comp in skyconfig.keys()):
        n_comp += 1
    #search for dust, synch, etc as pysm models
    if any('pysm_fg' in comp for comp in skyconfig.keys()):
        if any('d' in model for model in skyconfig['pysm_fg']):
            n_comp += 1
        if any('s' in model for model in skyconfig['pysm_fg']):
            n_comp += 1
    if any('not_pysm_fg' in comp for comp in skyconfig.keys()):
        n_comp += len(skyconfig['not_pysm_fg'])
        print('WARNING: there is a custom fg model!')

    print('Number of sky components: ', n_comp)
    return n_comp


def get_num_params(skyconfig, temp_is_fixed=True):
    '''
    This function defines the number of parameters in the foreground sky
    '''
    n_par = 0
    #search for dust, synch, etc as pysm models
    if any('pysm_fg' in comp for comp in skyconfig.keys()):
        if any('d' in model for model in skyconfig['pysm_fg']):
            if temp_is_fixed:
                n_par += 1
            else:
                n_par += 2
        if any('s' in model for model in skyconfig['pysm_fg']):
            n_par += 1
    if any('not_pysm_fg' in comp for comp in skyconfig.keys()):
            print('WARNING: specify this model and number of parameters!')
            pass
    
    print('Number of fg parameters: ', n_par)
    return n_par

def get_name_params(n_par, temp_is_fixed=True):
    '''
    This function return a list with the names of the parameters
    '''
    if n_par > 0: #there are foregrounds
        if n_par == 3:
            params = ['beta d','T d','beta s']
        elif n_par == 2:
            if temp_is_fixed == True:
                params = ['beta d','beta s']
            else:
                params = ['beta d','T d']
        else: #return a general list of parameters
            params = ['param {}'.format(i+1) for i in range(n_par)]
    else: #there's only cmb
        print('There are no parameters.')
        return 1

    return params


def eval_redu_chi_square_map(n_stk, npix, pixok, instrum_config, n_comp, n_par, A_beta, recons_maps, input_map, skyconfig, j, center, save_figs=True):
    '''
    Evaluates and returns the reduced chi square maps (Q and U) after the component separation. 
    '''
    chisq = np.zeros((n_stk, npix))
    chisq[:,~pixok] = hp.UNSEEN
    npixok = np.count_nonzero(pixok)
    #print('num freq ', instrum_config['nbands'])
    #print('npixok ', npixok)
    nside = hp.npix2nside(npix)
    
    if n_stk == 2:
        stk = ['Q','U']
    else:
        stk = ['I','Q','U']
        
    #eval reduced chi square pixel-by-pixel
    for istk in range(n_stk):
        #eval reconstructed frequency maps
        mapout = np.zeros((instrum_config['nbands'], npixok))
        if A_beta.ndim==3: #spatially varying parameters
            for icomp in range(n_comp):
                mapout += A_beta[:, :, icomp].T*recons_maps[icomp, istk, pixok] #matrix [Nf,Npixok]
        elif A_beta.ndim==2: #spatially constant parameters
            mapout = np.dot(A_beta, recons_maps[:, istk, pixok]) #matrix [Nf,Npixok]
        else:
            print('Error! Check mixing matrix!')
        #eval residual map (and plot it)
        mapout -= input_map[:,istk+1,pixok]
        if save_figs == True:
            plotfilename = './Delta_maps/Res_map_{}_{}_fgsky{}.png'.format(j+1, stk[istk], skyconfig['pysm_fg'])
            plot_and_save_delta_maps_over_frequency(npix, pixok, mapout, center, instrum_config, stk[istk], plotfilename)
        #divide by noise level at each frequency
        noise_per_pixel = np.sqrt(2)*instrum_config['depth_p']/(np.sqrt(hp.nside2pixarea(nside, degrees=True)) * 60)
        mapout /= noise_per_pixel[:,np.newaxis]
        #eval reduced chi square
        chisq[istk,pixok] = np.sum(mapout**2, axis=0)/(instrum_config['nbands']-n_par) #reduced chi square 

    return chisq


def plot_and_save_param_residual_maps(n_par, param_maps_th, param_maps, center, instrum_config, params, plotfilename):
    figure(figsize=(16,10))
    for i_par in range(n_par):
        res_par = param_maps[i_par,:] - param_maps_th[i_par,:]
        hp.gnomview(res_par, rot=center, reso=15, title=instrum_config['name']+': residual '+params[i_par], norm='hist', sub=(1,n_par,i_par+1))
    savefig(plotfilename)
    
    return 

def plot_and_save_cmb_residual_maps(n_stk, residual_maps_baseline, center, instrum_config, stk, plotfilename):
    figure(figsize=(16,10))
    for i_stk in range(n_stk):
        hp.gnomview(residual_maps_baseline[i_stk,:], rot=center,
                    reso=15, title=instrum_config['name']+': CMB residual '+stk[i_stk],
                    norm='hist', sub=(1,n_stk,i_stk+1))
    savefig(plotfilename)
    
    return

def plot_and_save_chisquare_maps(n_stk, chisqmap, center, instrum_config, stk, plotfilename):
    figure(figsize=(16,10))
    for i_stk in range(n_stk):
        hp.gnomview(chisqmap[i_stk,:], rot=center,
                    reso=15, title=instrum_config['name']+': chi square '+stk[i_stk],
                    cmap='jet', sub=(1,n_stk,i_stk+1), min=0, max=1) #norm='hist'
    savefig(plotfilename)
    
    return

def plot_and_save_delta_maps_over_frequency(npix, pixok, mapout, center, instrum_config, stk, plotfilename):
    figure(figsize=(16,10))
    mapoutfull = np.zeros((instrum_config['nbands'], npix))
    mapoutfull[:,~pixok] = hp.UNSEEN
    mapoutfull[:, pixok] = mapout
    for i_f in range(instrum_config['nbands']):
        hp.gnomview(mapoutfull[i_f,:], rot=center,
                    reso=15, title='{} {} GHz '.format(stk, instrum_config['frequency'][i_f]),
                    norm='hist', sub=(3,int(instrum_config['nbands']/3),i_f+1))
    savefig(plotfilename)
    
    return


def plot_and_save_chisquare_hist(n_stk, chisqmap, pixok, instrum_config, stk, plotfilename):
    figure(figsize=(16,10))
    for i_stk in range(n_stk):
        subplot(1,n_stk,1+i_stk)
        bin_val, bin_edge = np.histogram(chisqmap[i_stk,pixok], bins=int(np.sqrt(np.count_nonzero(pixok))))
        binscenters = np.array([0.5 * (bin_edge[i] + bin_edge[i+1]) for i in range(len(bin_edge)-1)])   
        bar(binscenters, bin_val, width=bin_edge[1] - bin_edge[0])
        title(instrum_config['name']+': '+stk[i_stk])
        xlabel(r'$\chi_{{red}}^{{2}}$')
        ylabel('Counts')
        vlines(0, 0, np.max(bin_val), color='k', linestyle='--')
        vlines(1, 0, np.max(bin_val), color='k', linestyle='--')
    savefig(plotfilename)
    
    return