#!/bin/bash

set -u
set -e

yaml_config=config.yaml
job_owner=$1
job_number=$2

sleep 60

python slurmytron.py --config ${yaml_config} --job-owner ${job_owner} --job-number ${job_number} --set-status started

# python job-running state

# code = 'command'
sleep 60

python slurmytron.py --config ${yaml_config} --job-owner ${job_owner} --job-number ${job_number} --set-status finished


# if code = 0 
#    python job-finished success state
# else
#    python job-finisged failes state
# end

echo 123
exit 0
 
