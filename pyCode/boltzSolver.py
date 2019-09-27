#!/usr/bin/env python3

"""

.. module:: boltzSolver
    :synopsis: This module contains the main methods for solving the Boltzmann equations 

:synopsis: This module contains the main methods for solving the Boltzmann equations
:author: Andre Lessa <lessa.a.p@gmail.com>

"""

import sys
from pyCode.AuxFuncs import gSTARS, gSTAR, getTemperature, getOmega, getDNeff, getPressure, Hfunc
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
                self.events.append(lambda x,y: -1)
                self.events.append(lambda x,y: -1)
            else:
                def fSuppressed(x,y,icomp=i):
                    if self.components[icomp].active:
                        return y[icomp]+100.
                    else:
                        return 1.
                def fEquilibrium(x,y,icomp=i):
#                     return 1.
                    return self.checkThermalEQ(x,y,icomp)
                self.events.append(fSuppressed) #Stop evolution particle if its number is too small
                self.events.append(fEquilibrium) #Stop evolution if particle is decoupling
        #Set flag so integration stops when any event occurs:
        for evt in self.events:
            evt.terminal = True
        
        t0 = time.time()
        #Compute initial values for variables:
        self.S = np.array([(2*pi**2/45)*gSTARS(T0)*T0**3])
        self.T = np.array([T0])
        self.x = np.array([0.])
        self.R = np.array([1.])
                
        #Guess initial values for the components (if not yet defined).
        #For simplicity assume radiation domination for checking thermal
        #equilibrium condition:
        MP = 1.22*10**19
        H = np.sqrt(8.*np.pi**3*gSTAR(T0)/90.)*T0**2/MP
        sigV = self.getSIGV(T0)
        neq = self.nEQ(T0)
        #Thermal equilibrium condition (if >1 particle is in thermal equilibrium):
        thermalEQ = neq*sigV/H
        for i,comp in enumerate(self.components):
            comp.active = True
            if not hasattr(comp,'n') or not len(comp.n):
                if thermalEQ[i] > 1:
                    comp.n = np.array([neq[i]])
                else:
                    comp.n = np.array([1e-20*neq[i]])
                    comp.Tdecouple = T0
                comp.rho = comp.n*comp.rEQ(T0)
            else: #Remove all entries from components except the last
                if len(comp.n) > 1:
                    logger.info("Resetting %s's number and energy densities to last value")
                comp.n = comp.n[-1:] 
                comp.rho = comp.rho[-1:]

        #Set thermal equilibrium flags:
        neq = self.nEQ(self.T[-1])
        for i,comp in enumerate(self.components):        
            if comp.n[-1] != neq[i] and abs(comp.n[-1]-neq[i])/neq[i] > 1e-4:
                logger.info("Particle %s starting decoupled" %comp)
                comp.thermalEQ = False
            else:
                logger.info("Particle %s starting in thermal equilibrium" %comp)
                comp.thermalEQ = True                
            
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
        self.y0 = np.hstack((Ni0,Ri0,[NS0])).tolist()
        self.norm = self.n[:,-1] #Set normalization (ni0) for each component
        self.normS = self.S[-1] #Set normalization (S0) for entropy
        
    def EvolveTo(self,TF,npoints=5000,dx=None,atol=1e-6,rtol=1e-3):
        """
        Evolve the components in component list from the re-heat temperature T0 to TF
        For simplicity we set  R0 = s0 = 1 (with respect to the notes).
        The solution is stored in self.solutionDict.
        Returns True/False if the integration was successful (failed)    
        """
        
        #Set initial conditions for equations:
        self.setInitialCond()

        t0 = time.time()
        #Solve differential equations:
        T0 = self.T[0]
        x0 = self.x[-1]
        #Estimate the final value of x (x=log(R/R0)) assuming conservation of entropy
        xf = log(T0/TF) + (1./3.)*log(gSTARS(T0)/gSTARS(TF)) #Evolve till late times
        tvals = np.linspace(x0,xf,npoints)
        y0 = self.y0
        logger.debug('Evolving from %1.3g to %1.3g with %i points' %(x0,xf,len(tvals)))
        maxstep = np.inf
        if dx:
            maxstep = (xf-x0)/dx
        r = integrate.solve_ivp(self.rhs,t_span=(x0,xf),y0=y0,atol=atol,rtol=rtol,
                                t_eval=tvals,method='BDF',dense_output=True,
                                events=self.events,max_step=maxstep)
        
        if r.status < 0:
            NS = r.y[-1][-1]
            T = getTemperature(r.t[-1],NS,self.normS)
            logger.error("Solution failed at temperature %1.3g" %T)
            logger.error("Error message from solver: %s" %r.message)
            return False


        self.updateSolution(r)
        
        continueEvolution = False        
        for i,evt in enumerate(r.t_events):
            comp = self.components[int(i/2)]
            if evt.size > 0:
                continueEvolution = True
                if np.mod(i,2):
                    logger.info("Integration restarted because %s left thermal equilibrium at x=%s (T = %1.3g GeV)" %(comp.label,str(evt),self.T[-1]))
                    comp.Tdecouple = self.T[-1]
                    comp.thermalEQ = False
                else:
                    logger.info("Integration restarted because the number density for %s became too small at x=%s (T = %1.3g GeV)" %(comp.label,str(evt),self.T[-1]))
                    comp.Tdecay = self.T[-1]
                    comp.active = False
        
        if continueEvolution and any(comp.active for comp in self.components):
            self.EvolveTo(TF, npoints-len(r.t), dx)
        else:
            logger.info("Solution computed in %1.2f s" %(time.time()-t0))                          
            if r.status < 0:
                logger.error(r.message)
                return False
    
        return True
    
    
    def rhs(self,x,y):
        """
        Defines the derivatives of the y variables at point x = log(R/R0).
        active = [True/False,...] is a list of switches to activate/deactivate components
        If a component is not active it does not evolve and its decay and
        energy density does not contribute to the other components.
        For simplicity we set  R0 = s0 = 1 (with respect to the notes).
        """

        isActive = self.active
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
        T = getTemperature(x,NS,self.normS)
        
        logger.debug('RHS: Computing number and energy densities for %i components' %nComp)
        #Current number densities:
        n = self.norm*np.exp(Ni)
        #Current energy densities:
        rho = n*Ri

        #Compute equilibrium densities:
        neq = self.nEQ(T)
        rEQ = self.rEQ(T)
        
        #Force equilibrium densities for components in thermal equilibrium:
        coupled = np.array([not comp.Tdecouple for comp in self.components])
        Ri[np.where(coupled)] = rEQ[np.where(coupled)]
        Ni[np.where(coupled)] = np.log(neq[np.where(coupled)]/self.norm[np.where(coupled)])
        n[np.where(coupled)] = neq[np.where(coupled)]
        rho[np.where(coupled)] = (neq*rEQ)[np.where(coupled)]

        #Compute ratio of equilibrium densities
        #(helps with numerical instabilities)
        #rNeq[i,j] = neq[i]/neq[j]
        rNeq = np.array([[compi.rNeq(T,compj) if compi.active and compj.active else 0. for compj in self.components] 
                         for compi in self.components])

        #Dictionary with label:index mapping:
        labelsDict = dict([[comp.label,i] for i,comp in enumerate(self.components)])

        #Compute Hubble factor:
        H = Hfunc(T,rho,isActive)
        logger.debug('RHS: Done computing component energy and number densities')
        logger.debug('n = %s, rho = %s, neq = %s' %(n,rho,neq))

        #Auxiliary weights:
        logger.debug('RHS: Computing weights')
        #Effective equilibrium densities and BRs:
        #NXth[i] = N^{th}_i:
        NXth = self.getNXTh(T,n,rNeq,labelsDict)
        #NXYth[i,j] = N^{th}_{ij}:
        NXYth = np.array([[compi.getNXYTh(T,n,rNeq,labelsDict,compj) if not compj is compi and compj.active else 0. for compj in self.components] 
                          for compi in self.components])
        #Effective branching ratio (Beff[i,j] = B^{eff}_{ij}:
        Beff = np.array([[compi.getTotalBRTo(T,compj) if not compj is compi and compj.active else 0. for compj in self.components] 
                         for compi in self.components])
        logger.debug('Done computing weights')

        widths = self.width(T)
        masses = self.mass(T)
        BRX = self.getBRX(T)
        sigmaV = self.getSIGV(T)

        # Derivative for entropy:
        logger.debug('Computing entropy derivative')     
        dNS = np.sum(isActive*BRX*widths*masses*(n-NXth))*exp(3.*x - NS)/(H*T*self.normS)
        if np.isinf(dNS):
            logger.warning("Infinity found in dNS at T=%1.2g. Will be replaced by a large number" %(T))
            dNS = np.nan_to_num(dNS)

        logger.debug('Done computing entropy derivative')

        #Derivatives for the Ni=log(ni/s0) variables:
        logger.debug('Computing Ni derivatives')
        dN = np.zeros(nComp)
        #Expansion term:
        RHS = -3*n
        #Decay term:
        RHS -= widths*masses*n/(H*Ri)
        #Inverse decay term:
        RHS += widths*masses*NXth/(H*Ri) #NXth should be finite if i -> j +..
        #Annihilation term:            
        RHS += sigmaV*(neq - n)*(neq + n)/H
        # i + j <-> SM + SM:
        sigVij = [[compi.getCOSIGV(T,compj) if not compj is compi and compj.active else 0. for compj in self.components] 
                  for compi in self.components]
        RHS += np.einsum('ij,ij->i',sigVij,np.outer(neq,neq)-np.outer(n,n))/H
        # i+i <-> j+j (sigVjj*rNeq[i,j]**2 should be finite)
        sigVjj = [[compi.getSIGVBSM(T,compj) if not compj is compi and compj.active else 0. for compj in self.components] 
                  for compi in self.components]
        RHS += (np.einsum('ij,j,ij->i',rNeq**2,n**2,sigVjj)-n**2*np.einsum('ij->i',sigVjj))/H
        # i+SM <-> j+SM (cRate*rNeq[i,j] should be finite)
        cRate = [[compi.getConvertionRate(T,compj) if not compj is compi and compj.active else 0. for compj in self.components] 
                 for compi in self.components]
        RHS += (np.einsum('ij,j,ij->i',rNeq,n,cRate)-n*np.einsum('ij->i',cRate))/H
        # j <-> i +SM (#NXYth[j,i] should be finite if j -> i +...)
        RHS += (np.einsum('ji,j,j,j->i',Beff,masses/Ri,widths,n)-np.einsum('ji,j,j,ji->i',Beff,masses/Ri,widths,NXYth))/H

        for i,compi in enumerate(self.components):
            if not isActive[i] and RHS[i] > 0.:
                logger.warning("Inactive component %s is being injected" %compi.label)
                    
        np.divide(RHS,n,out=dN,where=isActive)
	#Approximate derivative for thermal distribution:
        dN[np.where(coupled)] = (dNS/(3*T)-1/T)*Ri[np.where(coupled)]

        RHS = np.zeros(nComp)
        dR = np.zeros(nComp)
        #Derivatives for the rho/n variables (only for thermal components):
        for i,comp in enumerate(self.components):
            if not isActive[i]:
                continue
            mass = masses[i]
            RHS[i] = -3.*getPressure(mass,rho[i],n[i])  #Cooling term
            for j, compj in enumerate(self.components):
                if not isActive[j]:
                    continue
                if j == i:
                    continue
                massj = masses[j]
                widthj = widths[j]
                #Injection and inverse injection terms:
                RHS[i] += widthj*Beff[j,i]*massj*(1./2. - Ri[i]/Ri[j])*(n[j] - NXYth[j,i])/H #NXth[j,i] should finite if j -> i+..

        np.divide(RHS,n,out=dR,where=isActive)
	#Approximate derivative for thermal distribution:
        dR[np.where(coupled)] = (dNS/3-1)*((mass**2-Ri**2)/T + 3*Ri + 3*T)[np.where(coupled)]

        dy = np.hstack((dN,dR,[dNS]))
        logger.debug('T = %1.23g, dNi/dx = %s, dRi/dx = %s, dNS/dx = %s' %(T,str(dN),str(dR),str(dNS)))

        return dy

          
    def checkThermalEQ(self,x,y,icomp):
        
        coupled = self.components[icomp].thermalEQ
        active = self.components[icomp].active
        if not coupled or not active:
            return 1.0
        
        #Store the number of components:
        nComp = len(self.components)
        isActive = self.active
        #Ni = log(n_i/s_0)
        Ni = y[:nComp]
        #R = rho_i/n_i
        Ri = y[nComp:2*nComp]
        #NS = log(S/S_0)
        NS = y[-1]

        #Get temperature from entropy and scale factor:
        T = getTemperature(x,NS,self.normS)
        #Current number densities:
        n = self.norm*np.exp(Ni)
        #Current energy densities:
        rho = n*Ri
        #Compute equilibrium densities:
        neq = self.nEQ(T)
        #Compute ratio of equilibrium densities
        #(helps with numerical instabilities)
        #rNeq[i,j] = neq[i]/neq[j]
#         rNeq = np.array([[compi.rNeq(T,compj) if compi.active and compj.active else 0. for compj in self.components] 
#                          for compi in self.components])
#         #Dictionary with label:index mapping:
#         labelsDict = dict([[comp.label,i] for i,comp in enumerate(self.components)])
        #Compute Hubble factor:
        H = Hfunc(T,rho,isActive)
        #Effective equilibrium densities and BRs:
        #NXth[i] = N^{th}_i:
#         NXth = self.getNXTh(T,n,rNeq,labelsDict)
#         #NXYth[i,j] = N^{th}_{ij}:
#         NXYth = np.array([[compi.getNXYTh(T,n,rNeq,labelsDict,compj) if not compj is compi and compj.active else 0. for compj in self.components] 
#                           for compi in self.components])
#         #Effective branching ratio (Beff[i,j] = B^{eff}_{ij}:
#         Beff = np.array([[compi.getTotalBRTo(T,compj) if not compj is compi and compj.active else 0. for compj in self.components] 
#                          for compi in self.components])

#         widths = self.width(T)
#         masses = self.mass(T)

        sigmaV = self.getSIGV(T)
        sigVij = [[compi.getCOSIGV(T,compj) if not compj is compi and compj.active else 0. for compj in self.components] 
                  for compi in self.components]
        sigVjj = [[compi.getSIGVBSM(T,compj) if not compj is compi and compj.active else 0. for compj in self.components] 
                  for compi in self.components]
        cRate = [[compi.getConvertionRate(T,compj) if not compj is compi and compj.active else 0. for compj in self.components] 
                 for compi in self.components]

        #Compute thermal equilibrium force:
        Feq = np.zeros(nComp)
        #Annihilation term:            
        Feq += 2*sigmaV*neq
        # i + j <-> SM + SM:
        Feq += np.einsum('ij,j->i',sigVij,neq)
        # i+i <-> j+j (sigVjj*rNeq[i,j]**2 should be finite)
        Feq += np.einsum('i,j,ij->i',neq,1+(n/neq)**2,sigVjj)
        # i+SM <-> j+SM (cRate*rNeq[i,j] should be finite)
        Feq += np.einsum('j,ij->i',n/neq,cRate)
        Feq = abs(Feq/H)

        #Compute the non-equilibrium forces:
        Ft = np.zeros(nComp)
        # i + j <-> SM + SM:
        Ft += np.einsum('ij,j->i',sigVij,neq-n)
        # i+i <-> j+j (sigVjj*rNeq[i,j]**2 should be finite)
        Ft += np.einsum('i,j,ij->i',neq,(n/neq)**2-1,sigVjj)
        # i+SM <-> j+SM (cRate*rNeq[i,j] should be finite)
        Ft += np.einsum('j,ij->i',n/neq-1,cRate)
        
        #Add expansion term:
        Ft = abs(Ft/H)+3
        
        return (1e3*Ft/Feq-1.)[icomp]

  
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
        Tvalues = np.array([getTemperature(x,NSvalues[i],self.normS) for i,x in enumerate(r.t)])
        self.T = np.hstack((self.T,Tvalues))
        
        #Store the number and energy densities for each component:
	#(if the particle is coupled, use the equilibrium densities)
        for icomp,comp in enumerate(self.components):
            if not comp.active:
                n = np.array([np.nan]*len(r.t))
                rho = np.array([np.nan]*len(r.t))
            elif not comp.Tdecouple:
                n = np.array([comp.nEQ(T) for T in Tvalues])
                rho = n*np.array([comp.rEQ(T) for T in Tvalues])
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
        for comp in self.components:
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
            f.write('# %s: T(decouple)~= %s | T(decay)~= %s | Omega h^2 %s = %1.4g\n' %(comp.label,
                                                                                          comp.Tdecouple,comp.Tdecay,tag,omega))
            f.write('# \n')
        
        DNeff = 0.
        for comp in self.components:
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
        
