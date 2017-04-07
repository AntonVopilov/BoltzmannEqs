#!/usr/bin/env python

"""

.. module:: boltzEqs
    :synopsis: This module defines the Boltzmann equations 

:synopsis: This module defines the Boltzmann equations
:author: Andre Lessa <lessa.a.p@gmail.com>

"""

from AuxFuncs import Hfunc, getTemperature, getPressure
from math import exp, log, isnan
from parameters import Pi, Zeta3
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from assimulo.problem import Explicit_Problem
import numpy
import decimal
decimal.getcontext().prec = 28


class BoltzEqs(Explicit_Problem):
    """Class to hold the Boltzmann equations"""
    
#Sets the initial conditions and check for errors in input
    def __init__(self,compList,x0=None,y0=None,sw=None):
        Explicit_Problem.__init__(self)
        self.components = compList
#         self.solver = None
        
        if not x0 is None and not y0 is None: self.updateValues(x0,y0,sw)   #Set initial conditions

    def updateValues(self,x,y,sw):
        """Replace the variables in self.components and set the new initial conditions."""        
#Store new values:
        if len(y) != 2*len(self.components)+1:
            logger.error("Wrong number of variables. Must be equal to number of 2*components+1 (entropy)")
            return False
        N = y[:len(self.components)]
        R = y[len(self.components):-1]
        yEntropy = y[-1]
        for icomp,comp in enumerate(self.components):
            comp.evolveVars["N"] = N[icomp]
            comp.evolveVars["R"] = R[icomp]       
#Set initial conditions for next evolution                              
        self.y0 = N + R
        self.y0.append(yEntropy)
        self.t0 = x
        self.sw0 = sw


    #The right-hand-side function (rhs)  
    def rhs(self,x,y,sw):
        """
        Defines the derivatives of the y variables at point x = log(R/R0).
        sw = [True/False,...] is a list of switches to activate/deactivate components
        If a component is not active it does not evolve and its decay and
        energy density does not contribute to the other components.
        For simplicity we set  R0 = s0 = 1 (with respect to the notes).
        """

        n = []
        neq = []
        rho = []
        R = []
        nratio = {'radiation' : 1.}   #n/neq ratio dictionary
        NS = y[-1]
        T = getTemperature(x,NS)        
        for i,comp in enumerate(self.components):
            ni = exp(y[i])
            Ri = y[i + len(self.components)]
            if comp.Type == 'CO': rhoi = comp.mass(T)*ni
            else: rhoi = Ri*ni
            n.append(ni)
            neq.append(comp.nEQ(T))
            rho.append(rhoi)
            R.append(Ri)
            if neq[-1] > 0.: nratio[comp.ID] = ni/neq[-1]
            else: nratio[comp.ID] = 0.
        H = Hfunc(x,n,rho,NS,sw)
       
             
#Auxiliary weights:           
        N1th = [0.]*len(self.components)
        N2th = [0.]*len(self.components)
        Beff = [0.]*len(self.components)
        for i,comp in enumerate(self.components):
            N2th[i] = [0.]*len(self.components)
            Beff[i] = [0.]*len(self.components)                        
        for i,comp in enumerate(self.components):
            N1th[i] = comp.getNTh(T,nratio)
            for a,compA in enumerate(self.components):                                
                if a == i or not sw[a]: continue 
                N2th[a][i] = compA.getNTh(T,nratio,comp)
                Beff[a][i] = compA.getTotalBRTo(T,comp)

# Derivative for entropy:        
        dNS = 0.        
        for i,comp in enumerate(self.components):
            if not sw[i]: continue
            dNS += comp.getBRX(T)*comp.width(T)*comp.mass(T)*(n[i]-N1th[i])*exp(3.*x - NS)/(H*T)

             
#Derivatives for the Ni=log(ni/s0) variables:   
        dN = [0.]*len(self.components)        
        for i,comp in enumerate(self.components):
            if not sw[i]: continue
            width = comp.width(T)
            mass = comp.mass(T)
            RHS = -3.*n[i]     
            RHS += -width*mass*(n[i] - N1th[i])/(H*R[i])    #Decay term
            RHS += comp.getSource(T)/H  #Source term
            if comp.Type == 'weakthermal':                
                nrel = Zeta3*T**3/Pi**2
                RHS += comp.getSIGV(T)*nrel*(neq[i] - n[i])/H
            else: RHS += comp.getSIGV(T)*(neq[i]**2 - n[i]**2)/H  #Annihilation term      
            for a, compA in enumerate(self.components):
                if not sw[a]: continue
                if a == i: continue                                
                massA = compA.mass(T)
                widthA = compA.width(T)         
                RHS += widthA*Beff[a][i]*massA*(n[a] - N2th[a][i])/(H*R[a])  #Injection term                       
            
            dN[i] = RHS/n[i]    #Log equations
        

            

        dR = [0.]*len(self.components)
#Derivatives for the rho/n variables (only for thermal components):        
        for i,comp in enumerate(self.components):
            if not sw[i] or comp.Type == 'CO': continue                 
            mass = comp.mass(T)
            RHS = -3.*getPressure(mass,rho[i],n[i])/n[i]  #Cooling term
            for a, compA in enumerate(self.components):
                if not sw[a]: continue                
                if a == i: continue                
                massA = compA.mass(T)
                widthA = compA.width(T)
                RHS += widthA*Beff[a][i]*massA*(1./2. - R[i]/R[a])*(n[a]/n[i] - N2th[a][i]/n[i])/H  #Injection term
            
            dR[i] = RHS

        bigerror = False
        for val in y:
            if isnan(val) or abs(val) == float('inf'): bigerror = 1     
        for val in numpy.array(dN + dR + [dNS]):
            if not bigerror and (isnan(val) or abs(val) == float('inf')): bigerror = 2
        if bigerror:
#             os._exit(0)
            if bigerror == 1:  logger.warning("Right-hand called with NaN values.")
            if bigerror == 2:  logger.warning("Right-hand side evaluated to NaN.")
          
        return numpy.array(dN + dR + [dNS])
    
    
    def state_events(self,x,y,sw):
        """Checks for a discontinuous transition happened.\
        Possible discontinuities are: 
          * a CO component starts to oscillate\
          * a particle has decayed and its number density is effectively zero
        The transition vector must be zero when such a transition occurs.
        Also updates the absolute tolerance of the solver, if the variable's
        values go below it.
        """
        
        n = []
        rho = []
        for icomp,comp in enumerate(self.components):
            ni = exp(y[icomp])
            Ri = y[icomp + len(self.components)]            
            rhoi = Ri*ni
            n.append(ni)
            rho.append(rhoi)
        NS = y[-1]
        T = getTemperature(x,NS)                     
        transition = [1.]*len(y)
                 
         
#Check if a CO component started oscillating
        for icomp,comp in enumerate(self.components):
            if comp.Type != 'CO': continue
            else: transition[icomp] = Hfunc(x,n,rho,NS,sw)*3. - comp.mass(T)
            
#Check if any of the ni components is reaching zero:
        for icomp,comp in enumerate(self.components):
            if comp.width(T) == 0. or not sw[icomp]: continue        
            transition[len(self.components)+icomp] = 2.*y[icomp] + 200.

#Adjust absolute tolerance, so it always respects the relative tolerance:
        try:
            for icomp, comp in enumerate(self.components):
                if not sw[icomp]: continue
                self.solver.atol[icomp] =  abs(y[icomp])*self.solver.rtol
                self.solver.atol[icomp+len(self.components)] =  abs(y[icomp+(self.components)])*self.solver.rtol
            self.solver.atol[-1] =  abs(y[-1])*self.solver.rtol
        except: pass
                                 
        return numpy.array(transition)


    def handle_event(self,solver,event_info):
        """Activate/de-activate components when a discontinuous transition happens\
        and sets the new initial conditions.\             
        Possible discontinuities are: a CO component starts to oscillate.                 
        """
        
#Event happened because of discontinuity
        NS = solver.y[-1]
        T = getTemperature(solver.t,NS)
        for iev,event in enumerate(event_info[0]):
            if event == 0: continue
            if iev < len(self.components):   #Discontinuities due to coherent oscillations
                if self.components[iev].Type != 'CO':
                    logger.error("Discontinuity found for a non-CO component ("+self.components[iev].ID
                                     +"). Should not happen.")
                    return False
                else:
                    solver.sw[iev] = True
                    comp = self.components[iev]
                    comp.active = True 
                    comp.Tosc = T                       
                    initN = comp.getOscAmplitute(T)/comp.mass(T)
                    solver.y[iev] = log(initN)  #Initial condition for log(n/s0)
                    solver.y[iev+len(self.components)] = comp.mass(T) #Initial condition for log(rho/n)
            else:    #Discontinuities due to component decay                
                icomp = iev-len(self.components)
                if self.components[icomp].width(T) == 0.:
                    logger.error("Discontinuity found for a stable component ("+self.components[icomp].ID
                                      +"). Should not happen.")
                    return False
                self.components[icomp].Tdecay = T
                solver.sw[icomp] = False   #Deactivate particle
                
