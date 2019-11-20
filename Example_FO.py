#!/usr/bin/env python3

#Example to describe the main steps required to define the model and inpute paramaters
#and solve the boltzmann equations

#First tell the system where to find the modules:
import os
import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)




def main(parameterFile,outputFile,showPlot=True):
    """
    
    Main code to define the BSM contents and properties and solve the Boltzmann equations
    
    :param parameterFile: Path to the file defining the main model parameters
    :param outputFile: Path to the output file. If None, no results will be written.
    :param showPlot: If True, will show a simple plot for the evolution of the energy densities
    
    """

    from pyCode.component import Component
    from pyCode.boltzSolver import BoltzSolution
    import numpy as np
    from scipy.interpolate import interp1d
    

    #Get the model parameters (or define them here):
    TRH = 1e4
    TF = 1e-3
    
   
    #Annihilation rate for mediator
    data = np.genfromtxt('./width_and_medxs.dat',skip_header=5)
    conv = 0.8579e17

    sLog = lambda x: interp1d(data[:,0],np.log(data[:,1]*conv),
                        fill_value='extrapolate',bounds_error=False)(x)

    #Conversion rates for DM and mediator: 
    dofDM = -2 #Number of DM degrees of freedom (Majorana fermion)

    @np.vectorize
    def sigmaVJan(T):
        x = 500./T
        if x > data[:,0].max():
            return 0.
        sF = sLog(x)
        return np.exp(sF)
    
    #Define the components to be evolved and their properties:    
    dm = Component(label='DM',Type='thermal',dof=dofDM,
                   mass=500., sigVii=lambda T: 1.5e-1*sigmaVJan(T))
    compList = [dm]
    
    #dm.n = np.array([dm.nEQ(25.)])
    #mediator.n = np.array([mediator.nEQ(25.)])
    #dm.rho = np.array([dm.nEQ(25.)*dm.rEQ(25.)])
    #mediator.rho = np.array([mediator.nEQ(25.)*mediator.rEQ(25.)])
    
    #Evolve the equations from TR to TF
    solution = BoltzSolution(compList,TRH)
    solved = solution.EvolveTo(TF,npoints=5000)
    if not solved:
        logger.error("Error solving Boltzmann equations.")
        return
    
    #Print summary
    if outputFile:
        if os.path.isfile(outputFile):
            os.remove(outputFile)
        solution.printSummary(outputFile)
        solution.printData(outputFile)
    solution.printSummary()
    

if __name__ == "__main__":

    import argparse    
    ap = argparse.ArgumentParser( description=
            "Evolve Boltzmann equations for a simple non-thermal DM scenario" )
    ap.add_argument('-p', '--parameterFile', 
            help='name of parameter file, where most options are defined', default = 'parameters.ini')
    ap.add_argument('-o', '--outputFile', 
            help='name of output file (optional argument). If not define, no output will be saved', default=None)
    ap.add_argument('-P', '--plotResult', help='show simple plot for the evolution of densities',
            action='store_true',default = False)    
    
    args = ap.parse_args()
    main(args.parameterFile,args.outputFile,args.plotResult)
