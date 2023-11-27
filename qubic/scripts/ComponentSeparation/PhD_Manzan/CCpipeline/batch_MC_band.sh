#!/bin/bash

#  #SBATCH --array=0-9

#SBATCH --job-name=MC_cls        # Job name                                                                                                                             
#SBATCH --mem=3gb                    # Job memory request                                                                                                                    
#SBATCH --time=10:00:00               # Time limit hrs:min:sec                                                                                                                
#SBATCH --output=output_100_10.log

export NUMBA_NUM_THREADS=12
export MKL_NUM_THREADS=12
export NUMEXPR_NUM_THREADS=12
export OMP_NUM_THREADS=12
export OPENBLAS_NUM_THREADS=12
export VECLIB_MAXIMUM_THREADS=12
export PYOPERATORS_NO_MPI=12


export QUBIC_DATADIR=/sps/qubic/Users/emanzan/libraries/qubic/qubic/
export QUBIC_DICT=$QUBIC_DATADIR/dicts

source ~/.bashrc
conda activate qubic

python -u /sps/qubic/Users/emanzan/work-dir/CCpipeline/MC_compsep_to_cls_bandint.py $1 $2 $3 $4 $5 $6
#python -u /sps/qubic/Users/emanzan/work-dir/CCpipeline/MC_compsep_to_cls_bandint.py $1 ${SLURM_ARRAY_TASK_ID} $2 $3 $4 $5
