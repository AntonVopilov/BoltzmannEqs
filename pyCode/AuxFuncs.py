#!/usr/bin/env python

"""

.. module:: AuxFuncs
    :synopsis: This module provides auxiliary functions 

:synopsis: This module provides auxiliary functions
:author: Andre Lessa <lessa.a.p@gmail.com>

"""

import os,sys
from scipy import integrate, interpolate, optimize
from numpy import arange
from math import exp, sqrt, log, pi, log10
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
import warnings
import pickle
Tmin,Tmax = 1e-15,1e5 #min and max values for evaluating gSTAR

warnings.filterwarnings('error')


class interp1d_picklable:
    """
    class wrapper for piecewise linear function. Required for pickling a interp1d result.
    """
    def __init__(self, xi, yi, **kwargs):
        self.xi = xi
        self.yi = yi
        self.args = kwargs
        self.f = interpolate.interp1d(xi, yi, **kwargs)

    def __call__(self, xnew):
        return self.f(xnew)

    def __getstate__(self):
        return self.xi, self.yi, self.args

    def __setstate__(self, state):
        self.f = interpolate.interp1d(state[0], state[1], **state[2])
        
def printParameters(parameters,outFile=None):
    """
    Prints input parameters.
    
    :param parameters: dictionary with parameters labels and their values
    """        
    if outFile:
        f = open(outFile,'a')
        f.write('#-------------\n')
        f.write('# Parameters:\n')
        for par,val in sorted(parameters):
            f.write('# %s = %s\n' %(par,val))
        f.write('#-------------\n')            
  
        
def printSummary(compList,TF,outFile=None):
    """
    Prints basic summary of solutions.
    """
    #Solution summary:
    if isinstance(outFile,file):
        f = outFile    
    else:    
        f = open(outFile,'a')
        
    f.write('#-------------\n')
    f.write('# Summary\n')
    f.write('# TF=%s\n' %TF)
    for comp in compList:         
        mindelta, Tlast = None, TF
        if comp.Tdecay: Tlast = max(comp.Tdecay,TF)    
        for iT,T in enumerate(comp.evolveVars['T']):   #Get point closest to Tlast        
            if abs(T-Tlast) < mindelta or mindelta is None: iF, mindelta = iT, abs(T-Tlast)
        rhoF = comp.evolveVars['rho'][iF]
        nF = comp.evolveVars['n'][iF]
        Tfinal = comp.evolveVars['T'][iF]        
        omega = getOmega(comp,rhoF,nF,Tfinal)        
        if not comp.Tdecay: tag = '(@TF)'
        else: tag = '(@decay)'
        f.write('# %s: T(osc)= %s | T(decouple)= %s | T(decay)= %s | Omega h^2 %s = %s\n' %(comp.label,comp.Tosc,
                                                                                      comp.Tdecouple,comp.Tdecay,tag,omega))
        f.write('# \n')
    
    f.write('# Delta Neff (@TF) = %s\n' %sum([getDNeff(comp,TF) for comp in compList]))
    f.write('#-------------\n')


def printData(compList,outputFile=None):
    """
    Prints the evolution of number and energy densities of the species to the outputFile 
    """
    
    if outputFile:
        f = open(outputFile,'a')
        f.write('#-------------\n')
        f.write('# Header:\n')
        header = ['R','T (GeV)']
        for comp in compList:
            header += ['n_{%s} (GeV^{3})'%comp.label, '#rho_{%s} (GeV^{2})' %comp.label]
        maxLength = max([len(s) for s in header])
        line = ' '.join(str(x).center(maxLength) for x in header)
        f.write('# '+line+'\n')
        for i,R in enumerate(compList[0].evolveVars['R']):
            data = [R,compList[0].evolveVars['T'][i]]
            for comp in compList:
                data += [comp.evolveVars['n'][i],comp.evolveVars['rho'][i]]
            line = ' '.join(str('%.4E'%x).center(maxLength) for x in data)
            f.write(line+'\n')
        f.write('#-------------\n')

def getDataFrom(dataFile):    
    """
    Reads a datafile generated by printData, printSummary and printParameters
    and returns a dictionary with the information.
    """
    
    if not os.path.isfile(dataFile):
        logger.error('File %s not found' %dataFile)
        return None,None,None
    
    f = open(dataFile,'r')
    data = f.read()
    
    #Get parameters
    parDict = {}
    if 'Parameters' in data:
        ipar = data.find('Parameters')
        parameters = data[ipar:data.find('---',ipar)].split('\n')        
        for par in parameters:
            if not '=' in par: continue
            parameter,val = par.split('=')
            val = val.replace('\n','')
            try:
                val = eval(val)
            except: pass
            parameter = parameter.replace('#','').strip()
            parDict[parameter] = val
            
    #Get Summary
    summaryDict = {}
    if 'Summary' in data:
        ipar = data.find('Summary')
        summaryData = data[ipar:data.find('---',ipar)].split('\n')        
        for par in summaryData:
            par = par.replace('#','').strip()
            if not '=' in par: continue
            if par.count('=') == 1:
                par = par.split('=')
                summaryDict[par[0].strip()] = eval(par[1])
            elif '|' in par and ':' in par:
                compLabel = par.split(':')[0]
                summaryDict[compLabel] = {}
                vals = par.split(':')[1].split('|')
                for v in vals:
                    label,val = v.split('=')
                    label = label.strip()
                    try:
                        val = eval(val)
                    except:
                        val = val.strip()
                    summaryDict[compLabel][label] = val            

    #Get data
    dataDict = {}
    if 'Header' in data:
        ipar = data.find('Header')
        dataPts = data[ipar:data.find('---',ipar)]
        header = dataPts.split('\n')[1]
        header = header.split('  ')
        header = [h.strip() for h in header if h.replace('#','').strip()]
        dataDict = dict([[h,[]] for h in header])
    
        #Get data points    
        pts = dataPts.split('\n')[2:]
    
        for pt in pts:
            pt = pt.replace('#','')
            if not pt.strip():
                continue
            pt = pt.split(' ')
            pt = [eval(x) for x in pt if x.strip()]
            for i,val in enumerate(pt):
                dataDict[header[i]].append(val)

    return parDict,summaryDict,dataDict


def getOmega(comp,rho,n,T):
    """Compute relic density today, given the component, number density and energy density\
    at temperature T. """
    
    if comp.Tdecay and comp.Tdecay > T: return 0.
    
    Ttoday = 2.3697*10**(-13)*2.725/2.75  #Temperature today
    rhoh2 = 8.0992*10.**(-47)   # value of rho critic divided by h^2
    dx = (1./3.)*log(gSTARS(T)/gSTARS(Ttoday)) + log(T/Ttoday)   #dx = log(R/R_today), where R is the scale factor
    nToday = n*exp(-3.*dx)
    ns = log((2*pi**2/45)*T**3)  #entropy (constant) 
    
    if comp.Type == 'CO': return nToday*comp.mass(Ttoday)/rhoh2  #CO components have trivial (non-relativistic) solution 
               
    R0 = rho/n    
    Rmin = R0*exp(-dx)    #Minimum value for rho/n(Ttoday) (happens if component is relativistic today)
    Pmin = getPressure(comp.mass(Ttoday),Rmin*nToday,nToday)
      
           
    if abs(Pmin - Rmin*nToday/3.)/(Rmin*nToday/3.) < 0.01: RToday = Rmin  #Relativistic component today
    else:
        def Rfunc(R,x):            
            TF = getTemperature(x,ns)
            nF = n*exp(-3*x)   #Number density at x (decoupled solution)
            rhoF = R*nF         #Energy density at x                        
            return -3*getPressure(comp.mass(TF),rhoF,nF)/nF
        RToday = integrate.odeint(Rfunc, R0, [0.,24.], atol = comp.mass(Ttoday)/10.)[1][0]  #Solve decoupled ODE for R=rho/n
   
    return RToday*nToday/rhoh2

def getDNeff(comp,TF):
    """Computes the contribution from component comp to the number of effective neutrinos at temperature TF.
    Can only be used after the Boltzmann equations have been solved and the solutions stored in comp.evolveVars.
    Gives zero if T > 1 MeV (where neutrinos are still coupled)."""

#Ignore component if it has decayed before TF        
    if comp.Tdecay and comp.Tdecay > TF: return 0.
#Get the number and energy densities of comp at T:
    Tdelta = [abs(TF-T) for T in comp.evolveVars['T']]
    iF = Tdelta.index(min(Tdelta))    
    rho = comp.evolveVars['rho'][iF]
    n = comp.evolveVars['n'][iF]
    T = comp.evolveVars['T'][iF]
    mass = comp.mass(T)
    if T > 10.**(-3): return 0.    
    if mass == 0. or (n and rho and rho/(n*mass) > 2.): rhoRel = rho    
    else: rhoRel = 0.
    DNeff = rhoRel/(((pi**2)/15)*(7./8.)*((4./11.)**(4./3.))*T**4)
    return DNeff

def Hfunc(T, rhov, sw):
    """Compute the Hubble parameter, given the variables x=log(R/R0) and ni, rhoi and NS=log(S/S0) """
    
    MP = 1.22*10**19
    
    rhoActive = []
    for i, rho in enumerate(rhov):
        if not sw[i]: continue
        rhoActive.append(rho)  # energy density of each active component     
    rhoRad = (pi**2/30)*gSTAR(T)*T** 4  # thermal bath's energy density    
    rhoActive.append(rhoRad)
    rhoTot = sum(rhoActive)  # Total energy density    
    H = sqrt(8*pi*rhoTot/3)/MP
    
    return H


def getFunctions(pclFile):
    """
    Computes the g*(T), g*s(T) and temperature functions and saves
    them to a pickle file. Ignores all BSM effects to these functions
    :param pclFile: Name of pickle file to dump the functions
    """
    
    logger.info("Computing auxiliary functions. This calculation is done only once and the results will be stored in %s.\n" %pclFile)
    
    #Get points to evaluate gSTAR
    Tpts = [10**i for i in arange(log10(Tmin),log10(Tmax),0.01)]
    #Evaluate gSTAR and gSTARS at these points
    gSTARpts = [gSTARexact(T) for T in Tpts]
    gSTARSpts = [gSTARSexact(T) for T in Tpts]
    #Get interpolating functions:
    gSTAR = interp1d_picklable(Tpts,gSTARpts,fill_value = (gSTARpts[0],gSTARpts[-1]),
                               bounds_error=False)
    gSTARS = interp1d_picklable(Tpts,gSTARSpts,fill_value = (gSTARSpts[0],gSTARSpts[-1]),
                               bounds_error=False)
    #Evaluate (2*pi^2/45)*gstarS(T)*T^3 at these points:
    fpts = [log((2*pi**2/45.)*gSTARS(T)*T**3) for T in Tpts]
    #Get inverse function to compute temperature from 
    Tfunc =  interp1d_picklable(fpts,Tpts,fill_value='extrapolate')    
    f = open(pclFile,'w')
    pickle.dump(gSTAR,f)
    pickle.dump(gSTARS,f)
    pickle.dump(Tfunc,f)
    f.close()

def getTemperature(x,NS):
    
    xmin = log((2*pi**2/45.)*gSTARS(Tmin)*Tmin**3)
    xmax = log((2*pi**2/45.)*gSTARS(Tmax)*Tmax**3)
    xeff = NS - 3.*x
    if xeff < xmin:  #For T < Tmin, g* is constant
        return ((45./(2*pi**2))*exp(xeff)/gSTARS(Tmin))**(1./3.)
    elif xeff > xmax: #For T > Tmax, g* is constant
        return ((45./(2*pi**2))*exp(xeff)/gSTARS(Tmax))**(1./3.)
    else:    
        return Tfunc(xeff)

def getPressure(mass, rho, n):
    """Computes the pressure for a component, given its mass, its energy density and its number density"""

    R = rho/n    
    if R > 11.5*mass: return n*(R/3)  # Ultra relativistic limit
    if R <= mass: return 0.  # Ultra non-relativistic limit
    
# Expansion coefficients for relativistic/non-relativistic transition    
    aV = [-0.345998, 0.234319, -0.0953434, 0.023657, -0.00360707, 0.000329645, -0.0000165549, 3.51085*10.**(-7)]    
    Prel = n*(R/3)  # Relativistic pressure
    Pnonrel = (2.*mass/3.)*(R/mass - 1.)  # Non-relativistic pressure
    Pnonrel += mass*sum([ai*(R/mass - 1.)**(i+2)  for i, ai in enumerate(aV)])
    Pnonrel *= n
        
    return min(Prel, Pnonrel)  # If P2 > P1, it means ultra relativistic limit applies -> use P1

def gstarFunc(x, dof):
    """
    Auxiliary function to compute the contribution from a single particle to gSTAR.\
    x = mass/T, dof = number of degrees of freedom (positive/negative for bosons/fermions)
    """
            
    if x > 20.: res = 0.  # Particle has decoupled
    elif x > 10.**(-2):  # Near decoupling
        ep = -float(dof / abs(dof))
        epsilon = 0.01  # To avoid limits on end points
        a = 0. + epsilon
        b = (1. / x) * (1. - epsilon / 100.)
        res = integrate.romberg(lambda y: sqrt(1. - y ** 2 * x ** 2) / (y ** 5 * (exp(1. / y) + ep)), a, b,
                                tol=0., rtol=0.01, divmax=100, vec_func=False)
    else:
        if dof < 0: res = 5.6822  # Fully relativistic/coupled
        elif dof > 0: res = 6.49394
                        
    return res*abs(dof)*0.15399  # Result

def gSTARexact(T, interpol=True):
    """
    Computes exactly the number of relativistic degrees of freedom in thermal equilibrium with the thermal
    bath.
    interpol turns on/off the interpolation around the QCD phase trasition region.
    """

    gstar = 0.
# Define SM masses and degrees of freedom
    MassesGauge = {"W" : 80., "Z" : 91., "A" : 0.}
    DoFGauge = {"W" : 6, "Z" : 3, "A" : 2}
    MassesLeptons = {"electron" : 0.51 * 10.**(-3), "muon" : 0.1056, "tau" : 1.77, "neutrino" : 0.}
    DoFLeptons = {"electron" :-4, "muon" :-4, "tau" :-4, "neutrino" :-6}
    if T < 0.25:  # After QCD phase transition        
        MassesHadrons = {"pion" : 0.14, "eta" : 0.55, "rho" : 0.77, "omega" : 0.78, "kaon" : 0.5}
        DoFHadrons = {"pion" : 4, "eta" : 2, "rho" : 6, "omega" : 6, "kaon" : 4}
    else:  # Before QCD phase transition
        MassesHadrons = {"u" : 3.*10 ** (-3), "d" : 5.*10 ** (-3), "s" : 0.1, "c" : 1.3, "b" : 4.2, "t" : 173.3,
                         "g" : 0.}
        DoFHadrons = {"u" :-12, "d" :-12, "s" :-12, "c" :-12, "b" :-12, "t" :-12, "g" : 16}
    MassesSM = dict(MassesGauge.items() + MassesLeptons.items() + MassesHadrons.items())
    DoFSM = dict(DoFGauge.items() + DoFLeptons.items() + DoFHadrons.items())
# Add up SM degrees of freedom     
    for part in MassesSM:
        gstar += gstarFunc(MassesSM[part] / T, DoFSM[part])

# Correct for neutrino decoupling:
    if T <= 5.*10.**(-4):
        gstar += (-1. + (4. / 11.) ** (4. / 3.)) * gstarFunc(MassesSM["neutrino"] / T, DoFSM["neutrino"]) 
     
# Smooth discontinuous transitions:
    if interpol:
# QCD phase transition:
        finter = None
        if 0.15 < T < 0.3 and interpol:
            Tpts = [0.15, 0.3]
            gpts = [gSTARexact(Tpt, False) for Tpt in Tpts]        
            finter = interpolate.interp1d(Tpts, gpts, kind='linear')            
# Neutrino decoupling            
        elif  2.*10.**(-4) < T < 6.*10.**(-4):
            Tpts = [2.*10.**(-4), 6.*10 ** (-4)]
            gpts = [gSTARexact(Tpt, False) for Tpt in Tpts]        
            finter = interpolate.interp1d(Tpts, gpts, kind='linear')
# Replace gstar value by interpolation:
        if finter:
            gstar = finter(T)
    
    return gstar

def gSTARSexact(T):
    """
    Computes the number of relativistic degrees of freedom for computing the entropy density,\
    including the full MSSM spectrum, except for the lightest neutralino.
    """
 
    if T >= 10.**(-3):
        return gSTARexact(T)
    else:  # Correct for neutrino decoupling:        
        return gSTARexact(T) - (7. / 8.) * 6.*(4. / 11.) ** (4. / 3.) + (7. / 8.) * 6.*(4. / 11.)

def getTexact(x,NS):
    """Computes the temperature for the thermal bath from xeff = NS - 3*x, where
    x = log(R) and NS = log(S)."""

    xeff = NS - 3*x
    
    def TfuncA(T):
        """Auxiliary function, its zero implicitly determines T"""        
        return ((2.*pi**2)/45)*gSTARSexact(T)*T**3 - exp(xeff)

    Tmax = (45./(2.*pi**2))**(1./3.)*exp(xeff/3)  # Upper limit on T (since gSTARS > 1 always)
    Tmin = (45./(2.*pi**2*230.))**(1./3.)*exp(xeff/3)  # Lower limit on T (since gSTARS < 225 always)
    
    if gSTARSexact(Tmin) == gSTARSexact(Tmax):
        return (((2.*pi**2)/45)*gSTARSexact(Tmin))**(-1./3.)*exp(xeff/3)
            
    return optimize.brenth(TfuncA, Tmin, Tmax)



#Load auxiliary (pre-computed) functions:

if not os.path.isfile('gFunctions.pcl'):
    getFunctions('gFunctions.pcl')
 
f = open('gFunctions.pcl','r')
logger.info("Loading aux functions. Ignoring BSM corrections to g* and g*_S")
gSTAR = pickle.load(f)
gSTARS = pickle.load(f)
Tfunc = pickle.load(f)
f.close()
