#!/usr/bin/env python3

"""

.. module:: component
    :synopsis: This module defines the component class, which describe common properties for particle/field components 
        
:author: Andre Lessa <lessa.a.p@gmail.com>

"""

from pyCode.AuxDecays import DecayList
from scipy.special import kn,zetac
from numpy import exp,log,sqrt,pi
from  pyCode import AuxFuncs
from types import FunctionType
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MP = 1.22*10**19
Zeta3 = zetac(3.) + 1.

Types = ['thermal','CO', 'weakthermal']

class Component(object):
    """Main class to hold component properties.
    
    :param label: label for the component (can be anything)
    :param ID: a proper name for defining the component (must belong to IDs)
    :param Type: must be weakthermal, thermal or CO (weakly coupled thermal, thermal or coherent oscillating field)
    :param active: if component is active or not (True/False)
    :param dof: +/- Number of degrees of freedom (must be negative for fermions and positive for bosons)
    :param Tdecay: stores the temperature at which the particle starts to decay (approximate)
    :param Tosc: stores the temperature at which the particle starts to oscillate (if Type = CO)
    :param Tdecouple: stores the temperature at which the particle decouples (if Type = thermal/weakthermal)
    :param evolveVars: Stores the values of the variables used for evolution
    
    """
    
    def __init__(self,label,Type,dof,mass,decays=DecayList(),
                 sigmav = lambda x: 0., coSigmav = lambda x,y: 0.,
                 convertionRate = lambda x,y: 0., sigmavBSM = lambda x,y: 0.,
                 source = lambda x: 0., coherentAmplitute = lambda x: 0.):
        self.label = label
        self.Type = Type
        self.active = True
        self.dof = dof
        self.Tdecay = None
        self.Tosc = None
        self.Tdecouple = None
        self.sigmav = sigmav
        self.coSigmav = coSigmav
        self.convertionRate = convertionRate
        self.sigmavBSM = sigmavBSM
        self.source = source
        self.coherentAmplitude = coherentAmplitute

        if not Type or type(Type) != type(str()) or not Type in Types:
            logger.error("Please define proper particle Type (not "+str(Type)+"). \n Possible Types are: "+str(Types))
            return False

        #Check if given mass already is a function: 
        if isinstance(mass,FunctionType):
            self.mass = mass #Use function given
        elif isinstance(mass,int) or isinstance(mass,float):
            self.mass = lambda T: float(mass)  #Use value given for all T
        else:
            logger.error("Mass must be a number or a function of T")
            return False

        #Check if given decays already is a function: 
        if isinstance(decays,FunctionType):
            self.decays = decays #Use function given
        elif isinstance(decays,DecayList):
            self.decays = lambda T: decays #Use value given for all T
        else:
            logger.error("Decays must be a DecayList object or a function of T")
            return False

    def __str__(self):
        
        return self.label

    def getBRs(self,T):
        """
        Get the decays for a given temperature T
        """

        return self.decays(T) 

    def getBRX(self,T):
        """
        Returns the fraction of energy injected in the thermal bath by the component decay at temperature T
        """ 
       
        return self.getBRs(T).Xfraction
    
    def width(self,T):
        """
        Returns the component width at temperature T.
        """
          
        return self.getBRs(T).width
    
    def getTotalBRTo(self,T,comp):
        """
        Computes the total branching ratio to compoenent comp (sum BR(self -> comp + X..)*comp_multiplicity),
        including the multiplicity factor
        """

        if self is comp:
            return 0.

        brTot = 0.
        for decay in self.getBRs(T):
            if not comp.label in decay.fstateIDs: continue
            brTot += decay.fstateIDs.count(comp.label)*decay.br
        return brTot
            

    def getNXTh(self,T,n,rNeq,labelsDict):
        """        
        Computes the effective thermal number density of first type at temperature T:
          
        :param T: temperature (allows for T-dependent BRs)
        :param n: list of number densities
        :param rNeq: list with ratios of number densities
        :param labelsDict: Dictionary with the component label -> index in n,rNeq mapping

        :return: Effective thermal number density at temperature T of first type (N_X^{th})
        """

        #Compute BRs:
        Nth = 0.
        BRs = self.getBRs(T)
        #Index for self:
        i = labelsDict[self.label]
        neq = self.nEQ(T)
        #If the thermal equilibrium density of self is zero,
        #there is no inverse decay:
        if not neq:
            return 0.
        for decay in BRs:
            nprod = 1.
            if not decay.br:
                continue  #Ignore decays with zero BRs
            for label in decay.fstateIDs:
                if label in labelsDict:
                    j = labelsDict[label]
                    nprod *= rNeq[i,j]*n[j]*decay.br/neq
            Nth += nprod

        Nth *= neq

        return Nth

    def getNXYTh(self,T,n,rNeq,labelsDict,comp):
        """
        Computes the effective thermal number density of second type at temperature T:

        :param T: temperature (allows for T-dependent BRs)
        :param n: list of number densities
        :param rNeq: list with ratios of number densities
        :param labelsDict: Dictionary with the component label -> index in n,rNeq mapping
        :param comp: Component object.

        :return: Effective thermal number density at temperature T of second type for self -> comp (N_{XY}^{th})
        """

        norm = comp.getTotalBRTo(T,self)
        #If comp does not decay to self, return zero
        if not norm:
            return 0.

        #Compute BRs:
        Nth = 0.
        BRs = comp.getBRs(T)
        #Index for self:
        j = labelsDict[comp.label]
        neq = comp.nEQ(T)
        #If the thermal equilibrium density of comp is zero,
        #there is no inverse injection:
        if not neq:
            return 0.

        for decay in BRs:
            nprod = 1.
            if not decay.br:
                continue  #Ignore decays with zero BRs
            if not self.label in decay.fstateIDs:
                continue #Ignore decays which do not include self
            for label in decay.fstateIDs:
                if label in labelsDict:
                    i = labelsDict[label]
                    nprod *= rNeq[j,i]*n[i]*neq*decay.br

            Nth += nprod*decay.fstateIDs.count(self.label)

        Nth *= neq/norm

        return Nth

    def getSIGV(self,T):
        """
        Returns the thermally averaged annihilation cross-section self+self -> SM + SM
        at temperature T
        """
        
        return self.sigmav(T)


    def getCOSIGV(self,T,other):
        """
        Returns the thermally averaged co-annihilation cross-section self+other -> SM + SM
        at temperature T
        """
        
        if other is self:
            return 0.

        return self.coSigmav(T,other)

    def getConvertionRate(self,T,other):
        """
        Returns the thermally averaged annihilation rate self+SM -> other+SM
        at temperature T
        """

        if other is self:
            return 0.

        return self.convertionRate(T,other)

    def getSIGVBSM(self,T,other):
        """
        Returns the thermally averaged annihilation rate self+self -> other+other
        at temperature T
        """
        
        if other is self:
            return 0.
        
        return self.sigmavBSM(T,other)
        
    def nEQ(self,T):
        """Returns the equilibrium number density at temperature T. Returns zero for non-thermal components"""
        
        if not 'thermal' in self.Type:
            return 0.
        
        x = T/self.mass(T) 
        if x < 0.1:
            neq = self.mass(T)**3*(x/(2*pi))**(3./2.)*exp(-1/x)*(1. + (15./8.)*x + (105./128.)*x**2) #Non-relativistic
        elif x < 1.5:            
            neq = self.mass(T)**3*x*kn(2,1/x)/(2*pi**2) #Non-relativistic/relativistic
        else:
            if self.dof > 0: neq = Zeta3*T**3/pi**2   #Relativistic Bosons
            if self.dof < 0: neq = (3./4.)*Zeta3*T**3/pi**2   #Relativistic Fermions
            
        neq = neq*abs(self.dof)
        return neq

    def rNeq(self,T,other):
        """Returns the ratio of equilibrium number densities at temperature T nEQ_self/nEQ_other"""

        if not 'thermal' in self.Type:
            return 0.

        if self is other:
            return 1.

        x = T/self.mass(T)
        y = T/other.mass(T)
        if x < 0.1 and y < 0.1: #Both are non-relativistic
            r = (self.mass(T)/other.mass(T))**3
            r *= exp(1/y-1/x)
            r *= (x/y)**(3./2.)
            r *= (1. + (15./8.)*x + (105./128.)*x**2)/(1. + (15./8.)*y + (105./128.)*y**2)
        else:
            neqA = self.nEQ(T)
            neqB = other.nEQ(T)
            if not neqB:
                return None
            r = neqA/neqB

        return r

    def rEQ(self,T):
        """Returns the ratio of equilibrium energy and number densities at temperature T,\
        assuming chemical potential = 0."""

        x = T/self.mass(T)
        if x > 1.675:   #Ultra relativistic
            if self.dof < 0: return (7./6.)*pi**4*T/(30.*Zeta3)  #Fermions
            else: return pi**4*T/(30.*Zeta3)    #Bosons
        else:                                                   #Non-relativistic/relativistic
            return (kn(1,1/x)/kn(2,1/x))*self.mass(T) + 3.*T
    
    def isOscillating(self,T,H):
        """Checks if the component is coherent oscillating. If it is a thermal field,
        it returns False. If it is a CO oscillating field and if
        self.active AND 3*H(T) < self.mass, returns True."""
        
        if self.Type == 'CO' and self.active:
            if H*3. < self.mass(T): return True
            else: return False
        else: return False

    def hasDecayed(self):
        """Checks if the component has fully decayed"""
        
        return False   #!!!!FIX!!!!
        
        
    def getOscAmplitute(self,T):
        """Computes the oscillation amplitude for the component at temperature T.
        If the component is of Type thermal, returns None."""
        
        if self.Type != 'CO': return None
        else: return self.coherentAmplitute(T)
        
    def getInitialCond(self,T,components=[]):
        """
        Get initial conditions for component at temperature T, assuming the energy
        density is dominated by radiation.
        """
        
        H = sqrt(8.*pi**3*AuxFuncs.gSTAR(T)/90.)*T**2/MP
        
        N = None
        R = None
                
        if self.Type == 'thermal' or self.Type == 'weakthermal':
            coannTerm = 0. #Co-annihilation term
            bsmScatter = 0. #2<->2 scattering between BSM components
            convertion = 0. #i<->j convertion
            annTerm = self.getSIGV(T)*self.nEQ(T)/H #Annihilation term
            for comp in components:
                if comp is self:
                    continue
                if comp.Tdecouple:
                    continue
                coannTerm += self.getCOSIGV(T,comp)*self.nEQ(T)/H
                bsmScatter += self.getSIGVBSM(T,comp)*self.nEQ(T)/H
                convertion += self.getConvertionRate(T,comp)/H

            totalProdRate = annTerm+convertion+bsmScatter+coannTerm
            if totalProdRate < 2.:  #Particle starts decoupled
                logger.info("Particle %s starting decoupled" %self)
                self.Tdecouple = T
                initN =  1e-10*self.nEQ(T)
                N = log(initN)
            else: #Particle starts coupled
                logger.info("Particle %s starting in thermal equilibrium" %self)
                initN =  self.nEQ(T)
                N = log(initN)
            R = self.rEQ(T)
        else:
            self.Tdecouple = T  #CO particles are always decoupled
            if self.isOscillating(T,H):  #Particle starts oscillating
                self.Tosc = T
                initN = self.getOscAmplitute(T)/self.mass(T)
                N = log(initN)
                R = self.mass(T)            
            else:
                self.active = False   #Deactivate component if it does not start oscillating 
                N = 0.
                R = 0.
            
        return N,R
        