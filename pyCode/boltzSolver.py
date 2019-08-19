#!/usr/bin/env python3

"""

.. module:: boltzSolver
    :synopsis: This module contains the main methods for solving the Boltzmann equations 

:synopsis: This module contains the main methods for solving the Boltzmann equations
:author: Andre Lessa <lessa.a.p@gmail.com>

"""

import sys
from pyCode.AuxFuncs import gSTARS, getTemperature, getOmega, getDNeff, getPressure, Hfunc
from numpy import log,pi,exp
import numpy as np
from scipy import integrate
import logging
import random, time
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)
random.seed('myseed')


class BoltzSolution(object):
    
    def __init__(self,compList,T0):
        
        self.components = compList #List of components (species)
        self.ncomp = len(compList)
        
        #Define discontinuity events:            
        self.events = []
        for i,comp in enumerate(self.components):
            if not comp.active:
                self.events.append([-1,-1])
            else:
                self.events.append(lambda x,y:  y[i] + 100.) #Stop evolution particle if its number is too small
                self.events.append(lambda x,y: self.checkThermalEqFor(i,x,y)) #Stop evolution if particle is decoupling
        
        
        t0 = time.time()
        #Compute initial values for variables:
        self.S = np.array([(2*pi**2/45)*gSTARS(T0)*T0**3])
        self.T = np.array([T0])
        self.x = np.array([0.])
        self.R = np.array([1.])
        
        #Get initial values for the components (if not yet defined):
        for comp in compList:
            if not hasattr(comp,'n') or not len(comp.n):
                comp.n = np.array([comp.guessInitialCond(T0,self.compList)])
                comp.rho = np.array([comp.n*comp.rEQ(T0)])
            else: #Remove all entries from components except the last
                if len(comp.n) > 1:
                    logger.info("Resetting %s's number and energy densities to last value")
                comp.n = comp.n[-1:] 
                comp.rho = comp.rho[-1:] 
            
        #Set initial conditions for equations:
        self.setInitialCond()
        
        logger.info("Initial conditions computed in %s s" %(time.time()-t0))
        
    def __getattr__(self, attr):
        """
        If self does not contain the attribute
        and the attribute has not been defined for the components
        return an array with the values for each component.
        It also applies to methods.

        :param attr: Attribute name

        :return: Array with attribute values
        """

        if not all(hasattr(comp,attr) for comp in self.components):
            raise AttributeError("Components do not have attribute ``%s''" %attr)


        val = getattr(self.components[0],attr)
        if not callable(val):
            return np.array([getattr(br,attr) for br in self.components])

        def call(*args, **kw):
            return np.array([getattr(comp, attr)(*args, **kw) for comp in self.components])
        return call
        

    def setInitialCond(self):
        """
        Use the last entries in the entrory and the components number and energy density values
        to compute the initial conditions.
        """

        Ni0 = np.zeros(self.ncomp) #Initial conditions for Ni = log(ni/ni0)
        Ri0 = self.rho[:,-1]/self.n[:,-1] #Initial conditions for Ri = rhoi/ni
        NS0 = 0. #Initial condition for NS = log(S/S0)
        self.y0 = np.concatenate((Ni0,Ri0,[NS0])).tolist()
        self.norm = self.n[:,-1] #Set normalization (ni0) for each component
        self.normS = self.S[-1] #Set normalization (S0) for entropy

        
    def EvolveTo(self,TF,npoints=100,dx=300.):
        """
        Evolve the components in component list from the re-heat temperature T0 to TF
        For simplicity we set  R0 = s0 = 1 (with respect to the notes).
        The solution is stored in self.solutionDict.
        Returns True/False if the integration was successful (failed)    
        """

        t0 = time.time()
        #Solve differential equations:
        T0 = self.T[-1]
        x0 = self.x[-1]
        #Estimate the final value of x (x=log(R/R0)) assuming conservation of entropy
        xf = log(T0/TF) + (1./3.)*log(gSTARS(T0)/gSTARS(TF)) #Evolve till late times
        tvals = np.linspace(x0,xf,npoints)
        y0 = self.y0
        logger.debug('Evolving from',x0,'to',xf,'with',len(tvals),'points')
        maxstep = (xf-x0)/dx
        r = integrate.solve_ivp(self.rhs,t_span=(x0,xf),y0=y0,
                                t_eval=tvals,method='BDF',
                                events=self.events,max_step=maxstep)
        if r.status < 0:
            NS = r.y[-1][-1]
            T = getTemperature(r.t[-1],NS)
            logger.error("Solution failed at temperature %1.3g" %T)
            logger.error("Error message from solver: %s" %r.message)
            return False

        self.updateSolution(r)
        #Check for events (decayed particles or out of equilibrium transitions):
        if self.x[-1] < xf-maxstep:
            self.setInitialCond()
            self.EvolveTo(TF, npoints, dx)
        else:
            logger.info("Solution computed in %1.2f s" %(time.time()-t0))                          
            if r.status < 0:
                logger.error(r.message)
                return False
    
        return True
    
    
    def rhs(self,x,y):
        """
        Defines the derivatives of the y variables at point x = log(R/R0).
        isActive = [True/False,...] is a list of switches to activate/deactivate components
        If a component is not active it does not evolve and its decay and
        energy density does not contribute to the other components.
        For simplicity we set  R0 = s0 = 1 (with respect to the notes).
        """

        isActive = self.isActive
        logger.debug('Calling RHS with arguments:\n   x=%s,\n   y=%s\n and switches %s' %(x,y,isActive))

        #Store the number of components:
        nComp = len(self.components)

        #Ni = log(n_i/s_0)
        Ni = y[:nComp]
        #R = rho_i/n_i
        Ri = y[nComp:2*nComp]
        #NS = log(S/S_0)
        NS = y[-1]

        #Get temperature from entropy and scale factor:
        T = getTemperature(x,NS)

        logger.debug('RHS: Computing number and energy densities for %i components' %nComp)
        #Current number densities:
        n = self.norm*np.exp(Ni)
        #Current energy densities:
        rho = n*Ri

        #Compute equilibrium densities:
        neq = self.nEQ(T)

        #Compute ratio of equilibrium densities
        #(helps with numerical instabilities)
        #rNeq[i,j] = neq[i]/neq[j]
        rNeq = np.array([[compi.rNeq(T,compj) for compj in self.components] for compi in self.components])

        #Dictionary with label:index mapping:
        labelsDict = dict([[comp.label,i] for i,comp in enumerate(self.components)])

        #Compute Hubble factor:
        isActive = self.isActive
        H = Hfunc(T,rho,isActive)
        logger.debug('RHS: Done computing component energy and number densities')

        #Auxiliary weights:
        logger.debug('RHS: Computing weights')
        #Effective equilibrium densities and BRs:
        #NXth[i] = N^{th}_i:
        NXth = self.getNXTh(T,n,rNeq,labelsDict)
        #NXYth[i,j] = N^{th}_{ij}:
        NXYth = np.array([[compi.getNXYTh(T,n,rNeq,labelsDict,compj) for compj in self.components] for compi in self.components])
        #Effective branching ratio (Beff[i,j] = B^{eff}_{ij}:
        Beff = np.array([[compi.getTotalBRTo(T,compj) for compj in self.components] for compi in self.components])
        logger.debug('Done computing weights')

        # Derivative for entropy:
        logger.debug('Computing entropy derivative')     
        dNS = 0.
        for i,comp in enumerate(self.components):
            if not isActive[i]: continue
            dNS += comp.getBRX(T)*comp.width(T)*comp.mass(T)*(n[i]-NXth[i])*exp(3.*x - NS)/(H*T)
        if np.isinf(dNS):
            logger.warning("Infinity found in dNS at T=%1.2g. Will be replaced by a large number" %(T))
            dNS = np.nan_to_num(dNS)

        logger.debug('Done computing entropy derivative')

        #Derivatives for the Ni=log(ni/s0) variables:
        logger.debug('Computing Ni derivatives')
        dN = np.zeros(nComp)
        widths = self.width(T)
        masses = self.mass(T)
        #Expansion term:
        RHS = -3*n
        #Decay term:
        RHS += -widths*masses*n/(H*Ri)
        #Inverse decay term:
        RHS += widths*masses*NXth/(H*Ri) #NXth should be finite if i -> j +..
        #Annihilation term:
        sigmaV = self.getSIGV(T)
        RHS += sigmaV*(neq - n)*(neq + n)/H
        #Contributions from other BSM states:
        for i,compi in enumerate(self.components):
            for j,compj in enumerate(self.components):
                # i + j <-> SM + SM:
                sigVij = compi.getCOSIGV(T,compj)
                if sigVij:
                    RHS[i] += (neq[i]*neq[j]-n[i]*n[j])*sigVij/H #Co-annihilation
                # i+i <-> j+j:
                sigVjj = compi.getSIGVBSM(T,compj)
                if sigVjj:
                    RHS[i] += (rNeq[i,j]*n[j]-n[i])*(rNeq[i,j]*n[j]+n[i])*sigVjj/H #sigVjj*rNeq[i,j]**2 should be finite
                # i+SM <-> j+SM:
                cRate = compi.getConvertionRate(T,compj)
                if cRate:
                    RHS[i] += (rNeq[i,j]*n[j]-n[i])*cRate/H #cRate*rNeq[i,j] should be finite
                # j <-> i +SM:
                RHS[i] += Beff[j,i]*masses[j]*widths[j]*(n[j]-NXYth[j,i])/(H*Ri[j]) #NXYth[j,i] should be finite if j -> i +...

            if not self.isActive[i]:
                if RHS[i] < 0.:
                    continue
                else:
                    logger.warning("Inactive component %s is being injected" %compi.label)
            elif RHS[i]:
                dN[i] = np.float64(RHS[i])/np.float64(n[i])
                if np.isinf(dN[i]):
                    logger.warning("Infinity found at in dN[%s] at T=%1.2g. Will be replaced by a large number" %(comp.label,T))
                    dN[i] = np.nan_to_num(dN[i])


        RHS = np.zeros(nComp)
        dR = np.zeros(nComp)
        #Derivatives for the rho/n variables (only for thermal components):
        for i,comp in enumerate(self.components):
            if not isActive[i] or comp.Type == 'CO':
                continue
            mass = masses[i]
            RHS[i] = -3.*getPressure(mass,rho[i],n[i])  #Cooling term
            for j, compj in enumerate(self.components):
                if not isActive[j]: continue
                if j == i: continue
                massj = masses[j]
                widthj = widths[j]
                #Injection and inverse injection terms:
                RHS[i] += widthj*Beff[j,i]*massj*(1./2. - Ri[i]/Ri[j])*(n[j] - NXYth[j,i])/H #NXth[j,i] should finite if j -> i+..

            if RHS[i]:
                dR[i] = np.float64(RHS[i])/np.float64(n[i])
                if np.isinf(dR[i]):
                    logger.warning("Infinity found in dR[%s] at T=%1.2g. Will be replaced by a large number" %(comp.label,T))
                    dR[i] = np.nan_to_num(dR[i])

        dy = np.hstack((dN,dR,[dNS]))
        logger.debug('T = %1.23g, dNi/dx = %s, dRi/dx = %s, dNS/dx = %s' %(T,str(dN),str(dR),str(dNS)))

        return dy
    
                    
    def updateSolution(self,r):
        """
        Updates the solution in self.solutionDict if the
        integration was successful.
        :param r: Return of scipy.solution_ivp (Bunch object) with information about the integration
        """
        
        if r.status < 0:
            return #Do nothing

        #Store x-values
        self.x = np.hstack((self.x,r.t))       
        #Store R values:
        self.R = np.hstack((self.R,np.exp(r.t)))
        #Store the entropy values:
        S = self.normS*exp(r.y[-1,:])
        self.S = np.hstack((self.S,S))        
        #Store T-values
        NSvalues = r.y[-1,:]
        Tvalues = np.array([getTemperature(x, NSvalues[i]) for i,x in enumerate(r.t)])
        self.T = np.hstack((self.T,Tvalues))
        
        #Store the number and energy densities for each component:
        for icomp,comp in enumerate(self.compList):
            if not comp.active:
                n = np.array([np.nan]*len(r.t))
                rho = np.array([np.nan]*len(r.t))
            else:
                n = exp(r.y[icomp,:])*self.norm[icomp]
                rho = n*r.y[icomp+self.ncomp,:]
            comp.n = np.hstack((comp.n,n))
            comp.rho = np.hstack((comp.rho,rho))

    def printSummary(self,outFile=None):
        """
        Prints basic summary of solutions.
        """
        #Solution summary:
        if outFile:
            if hasattr(outFile,'write'):
                f = outFile    
            else:    
                f = open(outFile,'a')
        else:
            f = sys.stdout
            
        T = self.T
        TF = T[-1]
        f.write('#-------------\n')
        f.write('# Summary\n')
        f.write('# TF=%1.2g\n' %TF)
        for comp in self.compList:
            if comp.Tdecay:
                Tlast = max(comp.Tdecay,TF)
            else:
                Tlast = TF
            #Get point closest to Tlast    
            i = (np.abs(T - Tlast)).argmin()                    
            rhoF = comp.rho[i]
            nF = comp.n[i]
            Tfinal = T[i]
            omega = getOmega(comp,rhoF,nF,Tfinal)        
            if not comp.Tdecay:
                tag = '(@TF)'
            else:
                tag = '(@decay)'
            f.write('# %s: T(osc)= %s | T(decouple)~= %s | T(decay)~= %s | Omega h^2 %s = %1.2f\n' %(comp.label,comp.Tosc,
                                                                                          comp.Tdecouple,comp.Tdecay,tag,omega))
            f.write('# \n')
        
        DNeff = 0.
        for comp in self.compList:
            rho = comp.rho[-1]
            n = comp.n[-1]
            DNeff += getDNeff(comp, rho, n, TF)
                    
        f.write('# Delta Neff (T = %1.2g) = %1.2g \n' %(TF,DNeff))
        f.write('#-------------\n')
        f.close()
    
    def printData(self,outFile=None):
        """
        Prints the evolution of number and energy densities of the species to the outputFile 
        """
        
        if outFile:
            if hasattr(outFile,'write'):
                f = outFile    
            else:    
                f = open(outFile,'a')
            header = ['x','T','R','S']
            values = [getattr(self,label) for label in header]
            for comp in self.components:
                header += ['n_%s' %comp.label,'rho_%s' %comp.label]
                values.append(comp.n)
                values.append(comp.rho)

            maxLength = max([len(s) for s in header])
            header = ' '.join(str(x).center(maxLength) for x in header)
            if any(len(v) != len(values[0]) for v in values):
                logger.error("Data has distinct lengths and can not be written to file.")
                f.close()
                return False
            data = np.column_stack(values)
            f.write('#--------------\n')
            np.savetxt(f,data,delimiter=' ',header = header,fmt=('{:^%i}'%(maxLength-5)).format('%1.4E'))
            f.write('#--------------\n')    
            f.close()
        
