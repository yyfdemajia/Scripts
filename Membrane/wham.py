# Author: Samuel Genheden samuel.genheden@gmail.com

"""
Routines and classes to read in output files from umbrella sampling,
execute weighted histogram analysis method (WHAM) and calculate
the PMF along a 1D reaction coordinate
"""

import os
import tempfile
import shutil
import subprocess

import numpy as np
import numpy.random as random
import matplotlib.pylab as plt

KJMOL = 1
KCALMOL = 2
KB = {KJMOL : 0.00831446210, KCALMOL : 0.001982923700}
ECONV = {KJMOL : {KJMOL : 1.0, KCALMOL : 1.0/4.184}, KCALMOL : {KJMOL : 4.184, KCALMOL : 1.0}}
ELABEL = {KJMOL : "kJ/mol", KCALMOL : "kcal/mol"}
LABEL2UNIT = {"kJ/mol" : KJMOL, "kcal/mol" : KCALMOL}

#####################
# Histogram routines
#####################

def make_bins(data,nbins,boundaries=None) :
  """
  Make bin edges for histogramming

  Parameters
  ----------
  data : numpy array
    the data to be histogrammed
  nbins : int
    the number of bins to create
  boundaries : list of float, optional
    the minimum and maximum of the edges,
    if not supplied used the 99% confidence interval of the data (assuming normality)

  Results
  -------
  numpy array
    the bins edges
  """
  def get_99_conf(data) :
    mean = data.mean()
    std  = data.std()
    return (mean-2.58*std,mean+2.58*std)

  if boundaries == None :
    mn,ma = get_99_conf(data[0])
    for d in  data[1:] :
      lo,hi = get_99_conf(d)
      mn = min(mn,lo)
      ma = max(ma,hi)
  else :
    mn,ma = boundaries

  return np.linspace(mn,ma,nbins+1,endpoint=True)


def make_histograms(data,bins,boundaries=None) :
  """
  Histogram set of data using the same edges

  Mainly used by UmbrellaSim class, but could be useful in other circumstances

  Parameters
  ----------
  data : numpy array
    the data to be histogrammed
  bins : int or numpy array
    the number of bins to use or the edges of the histogram
  boundaries : list of float, optional
    the minimum and maximum of the edges

  Returns
  -------
  list of numpy array
    the histogram of the data
  numpy array
    the bin edges
  """
  if not np.iterable(bins) :
    bins = make_bins(data,bins,boundaries)

  histograms = [np.histogram(d,bins)[0] for d in data]
  return histograms,bins

def make_reweighted_histograms(data,weights,bins,boundaries=None) :
  """
  Weight-histogram set of data using the same edges

  Mainly used by UmbrellaSim class, but could be useful in other circumstances

  Parameters
  ----------
  data : numpy array
    the data to be histogrammed
  weights : numpy array
    the weight of the data
  bins : int or numpy array
    the number of bins to use or the edges of the histogram
  boundaries : list of float, optional
    the minimum and maximum of the edges

  Returns
  -------
  list of numpy array
    the histogram of the data
  numpy array
    the bin edges
  """
  if not np.iterable(bins) :
    bins = make_bins(data,bins,boundaries)

  histograms = [np.histogram(d,bins,weights=w)[0] for d,w in zip(data,weights)]
  return histograms,bins

#######################################################################
# Classes to read and analyse results from umbrella/zconst simulations
#######################################################################

class _ResultsFile :
  """
  Parent class to encapsulate a results file from an umbrella/zconst
  sampling simulation

  Internally, irrespectively of MD code, the units should
  be Angstroms for lengths and kcal/mol for energy

  Attributes
  ----------
  center : float
    the center of the umbrella potential
  samples : numpy array
    the samples from the simulation
  weight : float
    the weight of the umbrella potential
  """
  def __init__(self,center,weight=None,filename=None,**kwargs) :
    self.samples = None
    self.center = center
    self.weight = weight
    if filename is not None : self.read(filename,**kwargs)
  def __add__(self,other) :
    """ Adds the samples of another simulation onto this one
    """
    both = _ResultsFile(self.center,self.weight)
    both.samples = np.zeros(self.samples.shape[0]+other.samples.shape[0])
    both.samples[:self.samples.shape[0]] = self.samples
    both.samples[self.samples.shape[0]:] = other.samples
    return both
  def __radd__(self,other) :
    both = _ResultsFile(other.center,other.weight)
    both.samples = np.zeros(self.samples.shape[0]+other.samples.shape[0])
    both.samples[:self.other.shape[0]] = other.samples
    both.samples[self.other.shape[0]:] = self.samples
    return both
  def read(self,filename,**kwargs) :
    """ Should be implemented by sub-classes
    """
    pass
  def skip(self,nskip,ispart=True) :
    """
    Removes/skip samples at the start of the simulation

    Parameters
    ----------
    nskip : int
      the number or the proportion of samples to skip
    ispart : bool, optional
      if the nskip argument should be interpreted as
      the proportion of the total number of samples
    """
    if self.samples is None or (ispart and nskip < 2): return
    if ispart : nskip = int(np.floor(float(self.samples.shape[0])/float(nskip)))
    self.samples = self.samples[nskip+1:]
  def shorten(self,n,ispart=True) :
    """
    Removes samples at the end of the simulation

    Parameters
    ----------
    n : int
      the number or the proportion of samples to discard
    ispart : bool, optional
      if the n argument should be interpreted as
      the proportion of the total number of samples
    """
    if self.samples is None or (ispart and n < 2): return
    if ispart : n = int(np.floor(float(self.samples.shape[0])/float(n)))
    self.samples = self.samples[:n+1]
  def block_it(self,nblocks) :
    """
    Sub-sample/block the samples

    Parameters
    ----------
    nblocks : int
      the number of blocks

    Returns
    -------
    list of _ResultsFile objects
      the sub-samples/blocks of the original samples
    """
    if nblocks == 1 : return [self]
    blocks = []
    nitems = self.samples.shape[0]
    blocklen = int(np.floor(float(nitems)/float(nblocks)))
    for i in range(nblocks) :
      blocks.append(_ResultsFile(self.center,self.weight))
      blocks[-1].samples = self.samples[blocklen*i:min(blocklen*(i+1),nitems)]
    return blocks
  def synthesize(self) :
    """
    Replaces the samples with normal distributed data
    according to the mean and standard deviation of the orignal data
    """
    self._samples_orig = self.samples
    mean = self.samples.mean()
    std  = self.samples.std()
    self.samples = random.randn(self.samples.shape[0])*std + mean
  def lower(self) :
    """
    Returns the lower part of the 99% confidence interval
    """
    return self.samples.mean()-2.58*self.samples.std()
  def upper(self) :
    """
    Returns the upper part of the 99% confidence interval
    """
    return self.samples.mean()+2.58*self.samples.std()

class GromacsResultsFile(_ResultsFile) :
  """
  Read umbrella samples from a Gromacs pullx-files
  """
  def read(self,filename,**kwargs) :
    """
    Read a pullx-file

    Parameters
    ----------
    filename : string
      the name of the file
    **kwargs :
      colidx : the column index to parse
      isforces : if it is a pullf file rather than a pullx file
    """
    data = []
    if "colidx" in kwargs :
      colidx = kwargs["colidx"]
    else :
      colidx = 2
    # The pullf files do not have column 1
    if "isforces" in kwargs and kwargs["isforces"] :
      colidx = colidx - 1

    for line in open(filename,'r').readlines() :
      if not line[0] == "#" and not line[0] == "@" and len(line) > 4 :
        try :
          data.append(line.strip().split()[colidx])
        except :
          pass

    if "isforces" in kwargs and kwargs["isforces"] :
      self.samples =  np.array(data,dtype=float) / 10.0 * ECONV[KJMOL][KCALMOL] # Convert to kcal/mol/A
    else :
      self.samples = np.array(data,dtype=float)*10 # Convert to A
      if colidx != 2 :
        self.samples = -self.samples
      if self.center > 0 : self.samples = np.abs(self.samples)

class PlumedResultsFile(_ResultsFile) :
  """
  Read umbrella samples from a plumed colvars-file
  """
  def read(self,filename,**kwargs) :
    """
    Read a colvars-file

    Parameters
    ----------
    filename : string
      the name of the file
    **kwargs :
      colidx : the column index to parse
    """

    data = []

    if "colidx" in kwargs :
      colidx = kwargs["colidx"]-1 # To make it compatible with Gromacs umbrella output
    else :
      colidx = 1

    nread = 0
    with open(filename,"r") as f :
      line = f.readline()
      while line :
        if line[0] != "#" :
          data.append(line.strip().split()[colidx])
        line = f.readline()
    self.samples = np.array(data,dtype=float)*10 # Convert to A
    if colidx != 1 :
      self.samples = -self.samples
    if self.center > 0 and "expansion" not in kwargs : self.samples = np.abs(self.samples)

class LammpsResultsFile(_ResultsFile) :
  """
  Read umbrella samples from a Lammps colvars-file
  """
  def read(self,filename,**kwargs) :
    """
    Read a colvars-file

    Parameters
    ----------
    filename : string
      the name of the file
    **kwargs :
      stride : the stride to parse
    """
    if "stride" in kwargs :
      stride = kwargs["stride"]
    else :
      stride = -1

    data = []
    nread = 0
    with open(filename,"r") as f :
      line = f.readline()
      while line :
        if line[0] != "#" :
          nread = nread + 1
          if stride <= 0 or (stride > 0 and (nread == 1 or (nread-1) % stride == 0)) :
            if len(line.strip().split()) > 1 :
              data.append(line.strip().split()[1])
        line = f.readline()
    self.samples = np.array(data,dtype=float)

class SimpleEnergyFile(_ResultsFile) :
  """
  Read a simple energy file with total energies
  """
  def read(self,filename,**kwargs) :
    """
    Read a two-columned energy file, where the second column is parsed
    as total energies

    Parameters
    ----------
    filename : string
      the name of the file
    **kwargs :
      ignored at the moment
    """
    data = []
    with open(filename,"r") as f :
      line = f.readline()
      while line :
        if line[0] != "#" :
          data.append(line.strip().split()[1])
        line = f.readline()
    self.samples = np.array(data,dtype=float)

class UmbrellaSimulations() :
  """
  Class to encapsulate setup and results of a set of umbrella sampling simulations
  that can be combined with WHAM or Z-constraint method

  Attributes
  ----------
  temperature : float
    the temperature of the simulations
  unit : int
    the unit of the energy, should be either KJMOL or KCALMOL,
    defaults to KCALMOL
  boltzmann : float
    the Boltzmann constant in units of the energies
  kT : float
    the temperature factor, i.e. boltzmann*temperature
  centers : list of float
    the centers of the windows
  weights : list of float
    the weights of the windows
  samples : list of numpy array
    the samples of the simulations
  energies : list of numpy array
    the total energies of the simulation
  histograms : list of numpy array
    the histograms of the samples
  bins : numpy array
    the bin edges of the histogram
  """
  def __init__(self,temperature,unit=KCALMOL) :
    self.temperature = temperature
    self.unit = unit
    self.boltzmann=KB[unit]
    self.kT = self.boltzmann*self.temperature
    self.centers = []
    self.weights = []
    self.samples = []
    self.energies = []
    self.histograms = None
    self.bins = None
  def add(self,results,energies=None) :
    """
    Add a simulation to the set

    Parameters
    ----------
    results : _ResultsFile object
      the umbrella sampling results
    energies : numpy array, optional
      the total energy of the simulation
    """
    self.samples.append(results.samples)
    self.centers.append(results.center)
    self.weights.append(results.weight)
    if energies != None : self.energies.append(energies)
  def make_histograms(self,nbins,boundaries=None,weighted=True) :
    """
    Histogram the data

    If total energies are available and weighted is True, the Boltzmann
    weights of the total energies are used to weight the histogram

    Parameters
    ----------
    nbins : int
      the number of bins
    boundaries : list of float, optional
      the maximum and minimum values of the edges
    weighted : bool, optional
      whether to use to total energies to weight the histogram
    """
    if len(self.energies) == len(self.samples) and weighted :
      weights = [np.exp(-e/self.kT) for e in self.energies]
      self.histograms,self.bins = make_reweighted_histograms(self.samples,weights,nbins,boundaries)
    else :
      self.histograms,self.bins = make_histograms(self.samples,nbins,boundaries)
  def make_bins(self,nbins,boundaries=None) :
    """
    Create bin edges for the data

    Parameters
    ----------
    nbins : int
      the number of bins
    boundaries : list of float, optional
      the maximum and minimum values of the edges
    """
    if not self.bins is None : return
    self.bins = make_bins(self.samples,nbins,boundaries=boundaries)
  def pairwise_overlap(self) :
    """
    Calculates the pairwise overlap of the histograms

    If the histogram have not been made, nothing is done

    Returns
    -------
    numpy array
      the pairwise overlap
    """
    if self.histograms is None : return

    overlap = np.zeros(len(self.histograms)-1)
    pairwise_o = [np.sqrt(h1*h2) for h1,h2 in zip(self.histograms[:-1],self.histograms[1:])]
    pairwise_n    = [np.sqrt(s1.shape[0]*s2.shape[0]) for s1,s2 in zip(self.samples[:-1],self.samples[1:])]

    for i,(o,n) in enumerate(zip(pairwise_o,pairwise_n)) :
      overlap[i] = np.sum(o)/float(n)*100

    return overlap
  def plot_histograms(self,xlabel="z-distance",filename=None) :
    """
    Plot all histograms

    If the histogram have not been made, nothing is done

    Parameters
    ----------
    xlabel : string
      the label of the x-axis
    filename : string, optional
      if given, the figure is save as a PNG to this name

    Returns
    -------
    Figure object
      the figure created
    """
    if self.histograms is None or self.bins is None : return None

    hfig = plt.figure()
    z = (self.bins[:-1]+self.bins[1:])/2.0
    for s,h in zip(self.samples,self.histograms) :
      hfig.gca().plot(z,h/float(s.shape[0]))
    hfig.gca().set_xlim([z[0],z[-1]])
    hfig.gca().set_xlabel(xlabel)
    if filename is not None : hfig.savefig(filename)

    return hfig


##
# This is some code that was a test but never worked, shouldn't be used
#  def reweight_pmf(self,F) :
##    def bias(coor) :
#      dx = centers - coor
#      harmonic = 0.5*weights*dx*dx
#      return  harmonic

#    if self.whamobj is None : return

#    prob = self.whamobj.prob
#    centers = self.whamobj.centers
#    weights = self.whamobj.weights
#    bins = self.whamobj.bins
#    if bins.shape[0] > prob.shape[0] :
#      bins = (bins[1:]+bins[:-1])/2.0
#    nsamples = [s.shape[0] for s in self.samples]
#    nsamples = np.array(nsamples,dtype=int)

#    prob0 = np.zeros(prob.shape)
#    for i,corr in enumerate(bins) :
#      for j in range(len(self.samples)) :
#        b = bias(corr)
#        norm = nsamples*np.exp((F)/self.kT)
#        norm = prob[i]*norm.sum()
#        num =  nsamples[j]
#        prob0[i] = prob0[i]+num/norm
#    free = -self.kT*np.log(prob0)
#    free = free - free[0]
#    print self.whamobj.free-self.whamobj.free[0]
#    return free


class UmbrellaPmf :
  """
  Class to encapsulate an average PMF from umbrella simulations

  Attributes
  ----------
  simulations : list of UmbrellaSimulations
    the set of simulation sets
  z : numpy array
    the values of the reaction coordinate, it is assumed that all simulation sets
    have been histogrammed with the same edges
  pmfs : list of numpy array
    the pmfs of each UmbrellaSimultions object
  av : numpy array
    the average pmf
  std : numpy array
    the standard error of the pmf
  unit : int
    the unit of the energy, inherited from the simulation objects,
    assumes that all simulation sets have the same unit
  """
  def __init__(self) :
    self.simulations = None
    self.av = None
    self.std = None
    self.z = []
  def average(self,start=0,end=None) :
    if self.simulations is None : return
    if end is not None :
      self.av = np.mean(self.pmfs[:,start:end],axis=1)
      self.std = np.std(self.pmfs[:,start:end],axis=1)/np.sqrt(len(self.simulations[start:end]))
    else :
      self.av = np.mean(self.pmfs[:,start:],axis=1)
      self.std = np.std(self.pmfs[:,start:],axis=1)/np.sqrt(len(self.simulations[start:]))
  def change_unit(self,unit) :
    """
    Change unit of the PMFs

    Parameters
    ----------
    unit : int
      should be either KCALMOL or KJMOL
    """
    if unit == self.unit : return
    self.pmfs = self.pmfs * ECONV[self.unit][unit]
    self.av = self.av * ECONV[self.unit][unit]
    self.std = self.std * ECONV[self.unit][unit]
    self.kT = self.simulations[0].temperature*KB[unit]
    self.unit = unit
  def make(self,simulations,genclass,**kwargs) :
    self.simulations = simulations
    pmfs_and_z = [genclass(sim).pmf(**kwargs) for sim in simulations]
    self.z = pmfs_and_z[0][0]
    self.pmfs = [pz[1] for pz in pmfs_and_z]
    self.pmfs = np.array(self.pmfs).transpose()

    # Remove undefined z-values a set zero-pint
    idx = np.all(np.isfinite(self.pmfs),axis=1)
    self.z = self.z[idx]
    self.pmfs = self.pmfs[idx,:]
    if not "no_offset" in kwargs :
      self.pmfs = self.pmfs - self.pmfs[-1,:]

    self.unit = simulations[0].unit
    self.kT = simulations[0].kT

    self.average()
  def read(self,filename) :
    """
    Read the PMF from disc

    Parameters
    ----------
    filename : string
      the name of the file
    """
    av = []
    std = []
    z = []
    with open(filename,"r") as f :
      header = f.readline()
      label = header[header.index("(")+1:header.index(")")]
      self.unit = LABEL2UNIT[label]
      self.kT = KB[self.unit]*300

      line = f.readline()
      while line :
        zval,avval,stdval = line.strip().split()
        z.append(zval)
        av.append(avval)
        std.append(stdval)
        line = f.readline()
    self.z = np.array(z,float)
    self.av = np.array(av,float)
    self.std = np.array(std,float)

  def write(self,filename) :
    """
    Write the PMF to disc

    Parameters
    ----------
    filename : string
      the name of the file
    """
    with open(filename,"w") as f :
      f.write("#z-distance PMF Uncert. (%s)\n"%ELABEL[self.unit])
      for z,a,s in zip(self.z,self.av,self.std) :
        f.write("%.3f %.4f %.4f\n"%(z,a,s))
      f.close()
  def plot(self,fig=None,label="",ylabel=None,xlabel="z-distance [A]",filename=None,stride=10,color=None) :
    """
    Plot the average PMF

    Parameters
    ----------
    xlabel : string
      the label of the x-axis
    filename : string, optional
      if given, the figure is save as a PNG to this name

    Returns
    -------
    Figure object
      the figure created
    """
    if fig is None :
      fig = plt.figure()
    if color is None :
      fig.gca().errorbar(self.z[::stride],self.av[::stride],yerr=self.std[::stride],label=label)
    else :
      fig.gca().errorbar(self.z[::stride],self.av[::stride],yerr=self.std[::stride],label=label,color=color)
    #fig.gca().set_xlim([np.floor(self.z.min()-1.0),np.ceil(self.z.max()+1.0)])
    fig.gca().set_xlabel(xlabel)
    if ylabel is None :
      fig.gca().set_ylabel("PMF [%s]"%ELABEL[self.unit])
    else :
      fig.gca().set_ylabel(ylabel)
    if filename is not None : fig.savefig(filename)
    return fig
  def transfer_dg(self) :
    """
    Returns the transfer free energy and its standard error
    """
    return self.av[0],self.std[0]
  def waterlipid_barrier(self) :
    """
    Returns the water/lipid barrier, i.e. the difference between
    the water free energy and the minimum free energy
    """
    i = np.argmin(self.av)
    return self.av[i]-self.av[-1],np.sqrt(self.std[-1]**2+self.std[i]**2)
  def penetration_barrier(self) :
    """
    Returns the penetration barrier, i.e. the difference between the
    minimum free energy and the free energy at the centre of the bilayer
    """
    i = np.argmin(self.av)
    return self.av[0]-self.av[i],np.sqrt(self.std[0]**2+self.std[i]**2)
  def _trapz(self,x,av,stds) :
    # Trapezoid integration with error propagation
    intsum = 0.0
    w = 0.5*(x[0]+x[1])
    std = w**2*stds[0]**2
    for i in range(1,len(x)) :
      h = x[i]-x[i-1]
      intsum = intsum + h*(av[i]+av[i-1])/2.0
      if i == len(x) - 1 :
        w = 1.0 - 0.5*(x[i]+x[i-1])
      else :
        w = 0.5*(x[i+1]-x[i-1])
      std = std + w**2*stds[i]**2
    return intsum,np.sqrt(std)

  def standard_dg(self) :
    """
    Returns the standard binding free energy and its standard error
    """
    # JCTC, 2011, 7, 4175-4188

    expav = np.exp(-self.av/self.kT)
    expstd = np.abs(expav*(-self.std/self.kT))
    bndint,bndstd = self._trapz(self.z,expav,expstd)
    freeint = np.trapz(np.ones(self.z.shape[0]),self.z)
    bind = -self.kT * np.log(bndint/freeint)
    uncert = np.abs(-self.kT*bndstd/bndint)
    return bind,uncert

  def partition(self,water_density) :
    """
    Returns a partition coefficient and its error
    Paloncyova et al. JCTC, 2014
    """
    from scipy.interpolate import interp1d
    f = interp1d(water_density[:,0],water_density[:,1],kind="cubic")
    rho = f(self.z)
    rho = rho/rho.max()
    expav = np.exp(-self.av/self.kT) - rho
    expstd = np.abs(expav*(-self.std/self.kT))
    bndint,bndstd = self._trapz(self.z,expav,expstd)
    if bndint < 0 :
      expstd[expstd<0] = 0
      expav[expav<0] = 0
      bndint,bndstd = self._trapz(self.z,expav,expstd)
#    f = plt.figure(999)
    #f.gca().plot(water_density[:,0],water_density[:,1])
#    f.gca().plot(self.z,self.av)
#    f.gca().plot(self.z,rho,'--')
#    f.gca().plot(self.z,f2(self.z),'-*')
#    f.savefig("partition.png",format="png")
    return bndint,bndstd

###################################
# Classes that implements the WHAM
###################################

class _PmfGenerator(object) :
  """
  Class to encapsulate any algorithm to compute a PMF from
  a set of simulations at specific values of a reaction coordinate

  Attributes
  ----------
  simulations : UmbrellaSimulations object
    the simulations to analyze
  temperature : float
    the temperature of the simulations
  boltzmann : float
    the Boltzmann constant in units of the energies
  kT : float
    the temperature factor, i.e. boltzmann*temperature
  centers : list of float
    the centers of the umbrella windows
  weights : list of float
    the weights of the umbrella windows
  samples : list of numpy array
    the samples of the simulations
  energies : list of numpy array
    the total energies of the simulation
  """
  def __init__(self,simulations) :
    self.simulations = simulations
    self.samples    =  simulations.samples
    self.energies   =  simulations.energies
    self.centers =     np.array(simulations.centers)
    self.weights =     np.array(simulations.weights)
    self.temperature = simulations.temperature
    self.boltzmann =   simulations.boltzmann

    self.kT =     self.temperature*self.boltzmann
  def pmf(self,**kwargs) :
    """
    Computes the PMF and returns it

    Should be implemented by subclasses
    """
    pass

class Diffusion(_PmfGenerator) :
  """
  Class to estimate the diffusion by the Woolf and Roux method
  """
  def __init__(self,simulations) :
    super(Diffusion,self).__init__(simulations)
  def pmf(self,**kwargs) :
    diff = np.zeros(len(self.samples))
    dt = (kwargs["dt"] if "dt" in kwargs else 1)
    prev_tau = 0
    for i,(s,c) in enumerate(zip(self.samples,self.centers)) :
      diff[i] = s.var()/self._tau(s,dt)
    return self.centers,diff
  def _tau(self,z,dt) :
    dz = z-z.mean()
    acf = np.correlate(dz,dz,mode="full")
    acf = acf[len(acf)//2:]
    acf /= acf[0]
    import scipy.optimize as opt
    def double_exp(x,a0,a1,t0,t1) :
      return a0*np.exp(-x/t0)+a1*np.exp(-x/t1)
    def single_exp(x,a0,t0) :
      return a0*np.exp(-x/t0)
    x = np.arange(z.shape[0])
    try :
      popt,pcov = opt.curve_fit(double_exp,x,acf,p0=[10,10,0.1,0.1])
      acf_opt = double_exp(x,*popt)
    except :
      popt,pcov = opt.curve_fit(single_exp,x,acf,p0=[10,0.1])
      acf_opt = single_exp(x,*popt)
    t = np.trapz(acf_opt)*dt
    return np.abs(t)

class ZConst(_PmfGenerator) :
  """
  Class to encapsulate the z-constraint method

  Attributes
  ----------
  pmf : numpy array
    the free energy along the reaction coordinate
  diffusion : numpy array
    the diffusion coeffcient along the reaction coordinate
  """
  def __init__(self,simulations) :
    super(ZConst,self).__init__(simulations)
    self._pmf = None
    self._diffusion = None
  def pmf(self,**kwargs) :
    """
    Computes the PMF by WHAM iteration

    Attributes
    ----------
    **kwargs : dictionary of options
      compute : string
        what to compute, recognizes pmf and resistance

    Returns
    -------
    NumpyArray :
      the reaction coordinate
    NumpyArray :
      the free energy, PMF
    """
    self.compute_pmf()
    if "compute" not in kwargs or "compute" in kwargs and kwargs["compute"] == "pmf" :
      return self.centers,self._pmf
    else :
      self.compute_diffusion()
      resistance = np.divide(np.exp(self._pmf/self.kT),self._diffusion)
      return self.centers,resistance
  def compute_pmf(self) :
    avf = [s.mean() for s in self.samples]
    print len(self.samples)
    print avf,self.samples[0][0]
    print self.centers
    avf = np.array(avf[::-1])
    zrev = self.centers[::-1]
    pmf = np.zeros(avf.shape)
    for i,av in enumerate(avf) :
      pmf[i] = np.trapz(avf[:i+1],zrev[:i+1])
      print zrev[:i+1],pmf[i]
    self._pmf = pmf[::-1]
  def compute_diffusion(self) :
    self._diffusion = self.kT*self.kT*np.ones(self.centers.shape)
    for i,s in enumerate(self.samples) :
      df = s-s.mean()
      x = np.fft.fft(df)
      acf = np.real(np.fft.ifft(s*np.conjugate(s)))

class Wham(_PmfGenerator) :
  """
  Class to encapsulate the Weighted Histogram Analysis Method for a 1D reaction coordinate

  Attributes
  ----------
  histograms : list of numpy array
    the histograms of the samples
  bins : numpy array
    the bin edges of the histogram
  F : numpy array
    the bias free energies
  prob : numpy array
    the unbiased probability distribution
  free : numpy array
    the unbiased free energy distribution
  """
  def __init__(self,simulations) :
    super(Wham,self).__init__(simulations)
    self.histograms =  simulations.histograms
    self.bins =        simulations.bins
    self.F =      None
    self.prob =   None
    self.free =   None

  def iterate(self,tolerance=1E-5,maxiter=100000,verbose=True) :
    """
    Converge the bias free energies until self-consistency

    This is a virtual method that should be implemented by sub-classes

    Parameters
    ----------
    tolerance : float
      the maximum relative difference in the bias free energies
    maxiter : int
      stops after this many iterations, irrespectively of convergence
    verbose : bool, optional
      indicates if convergence information should be printed out
    """
    pass
  def pmf(self,**kwargs) :
    """
    Computes the PMF by WHAM iteration

    Attributes
    ----------
    **kwargs : dictionary of options
      not currently used

    Returns
    -------
    NumpyArray :
      the reaction coordinate
    NumpyArray :
      the free energy, PMF
    """
    self.iterate(verbose=False)
    z = (self.bins[0:-1]+self.bins[1:])/2.0
    return z,self.free

class ExternalWham(Wham) :
  """
  Converge the bias free energies until self-consistency
  do this by calling an external program which is faster
  than the pure Python implementation

  Uses the wham program from the Grossfield lab

  The wham program should be referenced by the environmental variable $WHAM
  """
  def iterate(self,tolerance=1E-5,maxiter=100000,verbose=True) :


    tempfolder = tempfile.mkdtemp(dir=os.getcwd())

    self._hasenergies = len(self.energies) == len(self.samples)
    self._write_datafiles(tempfolder)
    metafile = self._write_metafile(tempfolder)

    if self.bins is None :
      self.simulations.make_bins()
      self.bins = self.simulations.bins

    whamprog = os.getenv("WHAM","/home/sg6e12/Programs/wham/wham/wham")
    freefile = "%s/wham_free"%tempfolder
    logfile  = "%s/wham_log"%tempfolder

    whamcommand = "%s %.4f %.4f %d %.0E %.2f 0 %s %s >& %s"%(whamprog,self.bins[0],self.bins[-1],self.bins.shape[0]-1,tolerance,self.temperature,metafile,freefile,logfile)
    subprocess.call(whamcommand,shell=True)

    self._extract_output(freefile)

    shutil.rmtree(tempfolder)

  def _write_datafiles(self,tempfolder) :
    """ Write out all data to files in the tempfolder
    """
    for i,sample in enumerate(self.samples) :
      with open("%s/traj%d"%(tempfolder,i),"w") as f :
        for j,coor in enumerate(sample) :
          f.write("%d %.8f"%(j+1,coor))
          if self._hasenergies : f.write(" %.8f"%(self.energies[i][j]))
          f.write("\n")
  def _write_metafile(self,tempfolder) :
    """ Write out a WHAM metadata file
    """
    filename = "%s/wham_meta"%tempfolder
    with open(filename,"w") as f :
      for i in range(len(self.samples)) :
        f.write("%s/traj%d %.4f %.4f"%(tempfolder,i,self.centers[i],self.weights[i]))
        if self._hasenergies : f.write(" 1 %.4f"%self.temperature)
        f.write("\n")
    return filename
  def _extract_output(self,filename) :
    """ Extract results from WHAM
    """
    self.F = np.zeros(len(self.samples))
    self.prob = np.zeros(self.bins.shape[0]-1)
    self.free = np.zeros(self.bins.shape[0]-1)
    with open(filename,"r") as f :
      line = f.readline()
      # Look for the coordinates and extract the probability of each coordinate
      for i in range(self.bins.shape[0]-1) :
        cols = f.readline().strip().split()
        self.prob[i] = float(cols[3])
        self.free[i] = float(cols[1])
      # Look for the window free energies and extract them
      line = f.readline()
      for i in range(self.F.shape[0]) :
        cols = f.readline().strip().split()
        self.F[i] = float(cols[1])

class PyWham(Wham) :
  """
  Pure Python implementation of the WHAM algorithm,
  relatively slow but reproduces the wham program from the Grossfield lab
  """
  def iterate(self,tolerance=1E-5,maxiter=100000,verbose=True) :
    if self.histograms is None : return
    self.nwindows = len(self.histograms) # Store number of windows for convenience
    self.nsamples = [h.sum() for h in self.histograms] # The number of samples used to build the different histograms
    self.nbins = self.bins.shape[0]-1
    self.bins = (self.bins[1:]+self.bins[:-1])/2.0

    self.F = np.zeros(self.nwindows)#+self.addbias-self.addbias[0]
    self.__Fold = np.zeros(self.nwindows)
    self.prob = np.zeros(self.nbins)
    self.niter = 0
    while self.niter == 0 or not self.__converged(tolerance) :
      self.niter +=1
      if verbose and self.niter % 1 == 0 :
        print "Maximum error at iteration %d is %10E"%(self.niter,self.__maxerr())
        print "\t F: %s"%", ".join(["%.5f"%f for f in self.F])
      self.__Fold = np.array(self.F,copy=True)
      self.F = np.zeros(self.nwindows)
      self.__oneiter()
      if self.niter == maxiter :
        print "Maximum number iterations reached without finding a solution!"
        break
    # Normalize the probabilities
    self.prob = self.prob / self.prob.sum()
    # Calculate the free energy and normalize with respect to 0
    self.free = -self.kT*np.log(self.prob)
    self.free = self.free - self.free[0]
  def __calc_bias(self,coor) :
    """ Calculate harmonic bias potential
    """
    dx = self.centers - coor
    harmonic = 0.5*self.weights*dx*dx
    return  harmonic
  def __converged(self,tolerance) :
    """ Check if the free energies are converged
    """
    error = np.abs(self.F-self.__Fold)
    return error.max() <= tolerance
  def __maxerr(self) :
    """ Calculate the maximum error
    """
    error = np.abs(self.F-self.__Fold)
    return error.max()
  def __oneiter(self) :
    """ Perform one Wham iteration
    """
    # Loop over all edges of the histograms
    for i,coor in enumerate(self.bins) :
      # Use the previously calculated bias free energies (self.F)
      # to estimate the probability distribution
      num = 0.0
      denom = np.exp((self.__Fold-self.__calc_bias(coor))/self.kT)*self.nsamples
      for hi,histo in enumerate(self.histograms) :
        num = num + histo[i]
      self.prob[i] = num / denom.sum()
      # Update the bias free energies using the estimated probability distribution
      self.F = self.F + np.exp(-self.__calc_bias(coor)/self.kT)*self.prob[i]
    # Take the logarithm and remove an arbitrary constant
    self.F = -self.kT*np.log(self.F)
    self.F = self.F-self.F[-1]


# For debugging
if __name__ == '__main__' :

  import sys
  results = GromacsResultsFile(1.0,0.0,filename=sys.argv[1],isforces=True)
  results.skip(3)
  s = results.samples
  df = s-s.mean()
  x = np.fft.fft(df)
  acf = np.real(np.fft.ifft(s*np.conjugate(s)))/s.var()
  print s.shape,acf.shape,acf[0]
  f = plt.figure()
  a = f.add_subplot(311)
  a.plot(s)
  a = f.add_subplot(312)
  a.plot(acf)

  def fopt(x,A,B,tau0,tau1) :
    with np.errstate(invalid='ignore',over='ignore') :
      return A*np.exp(-x/tau0)+B*np.exp(-x/tau1)
  from scipy.optimize import curve_fit
  popt,pcov = curve_fit(fopt,np.arange(acf.shape[0]),acf,[0.5,0.5,0.1,0.1])
  print popt
  a = f.add_subplot(313)
  y = fopt(np.arange(acf.shape[0]),*popt)
  print y[0]
  a.plot(y[:10])
  a.plot(acf[:10])
  f.savefig("temp.png",format="png")
  print (KB[KJMOL]*300)**2*np.trapz(y)
