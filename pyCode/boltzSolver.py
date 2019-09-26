#!/usr/bin/env python3

"""

.. module:: boltzSolver
    :synopsis: This module contains the main methods for solving the Boltzmann equations 

:synopsis: This module contains the main methods for solving the Boltzmann equations
:author: Andre Lessa <lessa.a.p@gmail.com>

"""

from pyCode.EqFunctions import gSTARS, gSTAR, gSTARf
from pyCode.EqFunctions import T as Tfunc
import sympy as sp
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
                    return 1.
#                     return self.checkThermalEQ(x,y,icomp)
                self.events.append(fSuppressed) #Stop evolution particle if its number is too small
                self.events.append(fEquilibrium) #Stop evolution if particle is decoupling
        #Set flag so integration stops when any event occurs:
        for evt in self.events:
            evt.terminal = True
        
        t0 = time.time()
        #Compute initial values for variables:
        self.S = np.array([(2*np.pi**2/45)*gSTARS(T0)*T0**3])
        self.T = np.array([T0])
        self.x = np.array([0.])
        self.R = np.array([1.])
                
        #Guess initial values for the components (if not yet defined).
        #For simplicity assume radiatio            n domination for checking thermal
        #equilibrium condition:
        MP = 1.22*10**19
        H = np.sqrt(8.*np.pi**3*gSTARf(T0)/90.)*T0**2/MP
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
        
    def EvolveTo(self,TF,npoints=5000,dx=None,doJacobian=True):
        """
        Evolve the components in component list from the re-heat temperature T0 to TF
        For simplicity we set  R0 = s0 = 1 (with respect to the notes).
        The solution is stored in self.solutionDict.
        Returns True/False if the integration was successful (failed)    
        """
        
        #Set initial conditions for equations:
        self.setInitialCond()
        
        #Define Boltzmann equations and the jacobian (if required)
        self.rhs, self.jac = self.getRHS(doJacobian) 

        t0 = time.time()
        #Solve differential equations:
        T0 = self.T[0]
        x0 = self.x[-1]
        #Estimate the final value of x (x=log(R/R0)) assuming conservation of entropy
        xf = np.log(T0/TF) + (1./3.)*np.log(gSTARS(T0)/gSTARS(TF)) #Evolve till late times
        tvals = np.linspace(x0,xf,npoints)
        y0 = self.y0
        logger.debug('Evolving from %1.3g to %1.3g with %i points' %(x0,xf,len(tvals)))
        maxstep = np.inf
        if dx:
            maxstep = (xf-x0)/dx
        r = integrate.solve_ivp(self.rhs,t_span=(x0,xf),y0=y0,
                                t_eval=tvals,method='BDF',dense_output=True,
                                events=self.events,max_step=maxstep,jac=self.jac)
        
        if r.status < 0:
            NS = r.y[-1][-1]
            T = Tfunc(r.t[-1],NS,self.normS)
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
    
    def getRHS(self,doJacobian=True):
        
        """
        Obtain numerical functions for evaluating the right-hand side
        of the Boltzmann equations and its Jacobian (if required).
        First the algebraic equations are defined using Ni,Ri,NS and
        x as sympy variables. Derivatives of discontinuos or non-analytic
        functions are not explicitly computed and only evaluated numerically.
        
        :param doJacobian: Boolean specifying if the Jacobian of the differential
                           equations should be computed. If False, will return
                           None for the jacobian function.
                           
        :return: The RHS and Jacobian functions to be evaluated numerically.
        
        """
        
        #Store the number of components:
        nComp = len(self.components)

        #Define variables:        
        N = np.array(sp.symbols('N:%d'%nComp))
        R = np.array(sp.symbols('R:%d'%nComp))
        NS = sp.symbols('N_S')
        x = sp.symbols('x')
        T = Tfunc(x,NS,self.normS)
        
        #Planck constant:
        MP = sp.symbols('M_P')
        
        #Current number densities:
        n = self.norm*np.array([sp.exp(Ni) for Ni in N])
        #Current energy densities:
        rho = n*R
        
        #Compute equilibrium densities:
        neq = self.nEQ(T)
        
        #Compute ratio of equilibrium densities
        #(helps with numerical instabilities)
        #rNeq[i,j] = neq[i]/neq[j]
        rNeq = np.array([[compi.rNeq(T,compj) if compi.active and compj.active else 0. for compj in self.components] 
                         for compi in self.components])
        
        #Dictionary with label:index mapping:
        labelsDict = dict([[comp.label,i] for i,comp in enumerate(self.components)])
        isActive = self.active
        
        #Compute Hubble factor:
        rhoTot = np.sum(rho,where=isActive,initial=0)
        rhoRad = (sp.pi**2/30)*gSTAR(T)*T**4  # thermal bath's energy density    
        rho = rhoRad+rhoTot
        H = sp.sqrt(8*sp.pi*rho/3)/MP
                
        #Auxiliary weights:
        #Effective equilibrium densities and BRs:
        #NXth[i] = N^{th}_i:
        NXth = self.getNXTh(T,n,rNeq,labelsDict)
        widths = self.width(T)
        masses = self.mass(T)
        BRX = self.getBRX(T)
        sigmaV = self.getSIGV(T)
        
        # Derivative for entropy:
        dNS = np.sum(isActive*BRX*widths*masses*(n-NXth))*sp.exp(3.*x - NS)/(H*T*self.normS)
        
        #Derivatives for the Ni=log(ni/s0) variables:
        #Expansion term:
        RHS = -3*n
        #Decay term:
        RHS -= widths*masses*n/(H*R)
        #Inverse decay term:
        RHS += widths*masses*NXth/(H*R) #NXth should be finite if i -> j +..
        #Annihilation term:            
        RHS += sigmaV*(neq - n)*(neq + n)/H
        dN = sp.sympify(np.zeros(nComp)).as_mutable()
        for i,rhs in enumerate(RHS):
            if isActive[i]:
                dN[i] = rhs/n[i]

        RHS = sp.sympify(np.zeros(nComp)).as_mutable()
        #Derivatives for the rho/n variables (only for thermal components):
        for i,comp in enumerate(self.components):
            if not isActive[i]:
                continue
            RHS[i] = -3.*n[i]*comp.Pn(T,R[i])  #Cooling term

        dR = sp.sympify(np.zeros(nComp)).as_mutable()
        for i,rhs in enumerate(RHS):
            if isActive[i]:
                dR[i] = rhs/n[i]

        dy = np.hstack((dN,dR,[dNS])) #Derivatives
        yv = np.hstack((N,R,[NS])) #y-variables
        
        #Convert the algebraic equation in a numerical equation:
        rhsf = sp.lambdify([x,yv],dy, 
                          modules=[{'M_P' : 1.22e19},'numpy','sympy'])

        logger.debug('Done computing equations')
        
        #Compute the Jacobian (if required)
        if doJacobian:
            jac = sp.Matrix(dy).jacobian(yv).tolist()
            jacf = sp.lambdify([x,yv],jac,
                               modules=[{'M_P' : 1.22e19},'numpy','sympy'])
            logger.debug('Done computing Jacobian')
        else:
            jacf = None
            
        return rhsf,jacf

    
#     def rhs(self,x,y):
#         """
#         Defines the derivatives of the y variables at point x = log(R/R0).
#         active = [True/False,...] is a list of switches to activate/deactivate components
#         If a component is not active it does not evolve and its decay and
#         energy density does not contribute to the other components.
#         For simplicity we set  R0 = s0 = 1 (with respect to the notes).
#         """
# 
#         isActive = self.active
#         logger.debug('Calling RHS with arguments:\n   x=%s,\n   y=%s\n and switches %s' %(x,y,isActive))
# 
#         #Store the number of components:
#         nComp = len(self.components)
# 
#         #Ni = log(n_i/s_0)
#         Ni = y[:nComp]
#         #R = rho_i/n_i
#         Ri = y[nComp:2*nComp]
#         #NS = log(S/S_0)
#         NS = y[-1]
# 
#         #Get temperature from entropy and scale factor:
#         T = Tfunc(x,NS,self.normS)
#         
#         logger.debug('RHS: Computing number and energy densities for %i components' %nComp)
#         #Current number densities:
#         n = self.norm*np.exp(Ni)
#         #Current energy densities:
#         rho = n*Ri
# 
#         #Compute equilibrium densities:
#         neq = self.nEQ(T)
# 
#         #Compute ratio of equilibrium densities
#         #(helps with numerical instabilities)
#         #rNeq[i,j] = neq[i]/neq[j]
#         rNeq = np.array([[compi.rNeq(T,compj) if compi.active and compj.active else 0. for compj in self.components] 
#                          for compi in self.components])
# 
#         #Dictionary with label:index mapping:
#         labelsDict = dict([[comp.label,i] for i,comp in enumerate(self.components)])
# 
#         #Compute Hubble factor:
#         H = Hfunc(T,rho,isActive)
#         logger.debug('RHS: Done computing component energy and number densities')
#         logger.debug('n = %s, rho = %s, neq = %s' %(n,rho,neq))
# 
#         #Auxiliary weights:
#         logger.debug('RHS: Computing weights')
#         #Effective equilibrium densities and BRs:
#         #NXth[i] = N^{th}_i:
#         NXth = self.getNXTh(T,n,rNeq,labelsDict)
#         logger.debug('Done computing weights')
# 
#         widths = self.width(T)
#         masses = self.mass(T)
#         BRX = self.getBRX(T)
#         sigmaV = self.getSIGV(T)
# 
#         # Derivative for entropy:
#         logger.debug('Computing entropy derivative')     
#         dNS = np.sum(isActive*BRX*widths*masses*(n-NXth))*exp(3.*x - NS)/(H*T*self.normS)
#         if np.isinf(dNS):
#             logger.warning("Infinity found in dNS at T=%1.2g. Will be replaced by a large number" %(T))
#             dNS = np.nan_to_num(dNS)
# 
#         logger.debug('Done computing entropy derivative')
# 
#         #Derivatives for the Ni=log(ni/s0) variables:
#         logger.debug('Computing Ni derivatives')
#         dN = np.zeros(nComp)
#         #Expansion term:
#         RHS = -3*n
#         #Decay term:
#         RHS -= widths*masses*n/(H*Ri)
#         #Inverse decay term:
#         RHS += widths*masses*NXth/(H*Ri) #NXth should be finite if i -> j +..
#         #Annihilation term:            
#         RHS += sigmaV*(neq - n)*(neq + n)/H
#         np.divide(RHS,n,out=dN,where=isActive)
# 
#         RHS = np.zeros(nComp)
#         dR = np.zeros(nComp)
#         #Derivatives for the rho/n variables (only for thermal components):
#         for i,comp in enumerate(self.components):
#             if not isActive[i]:
#                 continue
#             RHS[i] = -3.*comp.getPressure(T,rho[i],n[i])  #Cooling term
#             for j, compj in enumerate(self.components):
#                 if not isActive[j]:
#                     continue
#                 if j == i:
#                     continue
# 
#         np.divide(RHS,n,out=dR,where=isActive)
# 
#         dy = np.hstack((dN,dR,[dNS]))
#         logger.debug('T = %1.23g, dNi/dx = %s, dRi/dx = %s, dNS/dx = %s' %(T,str(dN),str(dR),str(dNS)))
# 
#         return dy


#     def jac(self,x,y):
#         """
#         Computes the Jacobian for the y  equations.
#         """
#         
#         isActive = self.active
#         logger.debug('Calling Jacobian with arguments:\n   x=%s,\n   y=%s\n and switches %s' %(x,y,isActive))
# 
#         #Store the number of components:
#         nComp = len(self.components)
# 
#         #Ni = log(n_i/s_0)
#         Ni = y[:nComp]
#         #R = rho_i/n_i
#         Ri = y[nComp:2*nComp]
#         #NS = log(S/S_0)
#         NS = y[-1]
# 
#         #Get temperature from entropy and scale factor:
#         T = Tfunc(x,NS,self.normS)
#         
#         #Current number densities:
#         n = self.norm*np.exp(Ni)
#         #Current energy densities:
#         rho = n*Ri
# 
#         #Compute equilibrium densities:
#         neq = self.nEQ(T)
# 
#         #Compute Hubble factor:
#         H = Hfunc(T,rho,isActive)
# 
#         sigmaV = self.getSIGV(T)
# 
#         #Derivative for equations:
#         delta = np.identity(nComp)
#         
#         #Derivative for number equations:
#         dFNidNj = -np.einsum('ij,i,i,i->ij',delta,(neq/n)**2+1,sigmaV,n)/H
#         dFNidRj = np.zeros((nComp,nComp))
#         dFNidNS = np.zeros(nComp)
#         
#         #Derivative for energy ratio equations:
#         dFRidNj = np.zeros((nComp,nComp))
#         dFRidRj = np.zeros((nComp,nComp))
#         dFRidNS = np.zeros(nComp)
#         
#         #Derivative for entropy equation:
#         dFNSdNj = np.zeros(nComp)
#         dFNSdRj = np.zeros(nComp)
#         dFNSdNS = 0.
# 
#         # Full Jacobian:
#         JAC = np.zeros((nComp*2+1,nComp*2+1))
#         JAC[:nComp,:nComp] = dFNidNj
#         JAC[:nComp,nComp:2*nComp] = dFNidRj
#         JAC[:nComp,2*nComp] = dFNidNS
#         
#         JAC[3:2*nComp,:3] = dFRidNj
#         JAC[3:2*nComp,3:2*nComp] = dFRidRj
#         JAC[3:2*nComp,2*nComp] = dFRidNS
#         
#         JAC[2*nComp,:nComp] = dFNSdNj
#         JAC[2*nComp,nComp:2*nComp] = dFNSdRj
#         JAC[2*nComp,2*nComp] = dFNSdNS
# 
#         return JAC
  
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
        S = self.normS*np.exp(r.y[-1,:])
        self.S = np.hstack((self.S,S))        
        #Store T-values
        NSvalues = r.y[-1,:]
        Tvalues = np.array([Tfunc(x,NSvalues[i],self.normS) for i,x in enumerate(r.t)])
        self.T = np.hstack((self.T,Tvalues))
        
        #Store the number and energy densities for each component:
        #(if the particle is coupled, use the equilibrium densities)
        for icomp,comp in enumerate(self.components):
            if not comp.active:
                n = np.array([np.nan]*len(r.t))
                rho = np.array([np.nan]*len(r.t))
            else:
                n = np.exp(r.y[icomp,:])*self.norm[icomp]
                rho = n*r.y[icomp+self.ncomp,:]
            comp.n = np.hstack((comp.n,n))
            comp.rho = np.hstack((comp.rho,rho))

