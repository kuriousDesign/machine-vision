# SETTING UP FOR DEVELOPMENT
## Install venv tools
sudo apt-get update && sudo apt-get install -y python3-bpfcc bpfcc-tools libbpfcc-dev linux-headers-$(uname -r)

## Create venv using Python 3.12 
python3.12 -m venv venv (Ubuntu)
py -3.12 -m venv venv (Windows)

## Activate venv
source venv/bin/activate (Ubuntu)
venv\Scripts\activate   (this is for windows)

## Upgrade pip
pip install --upgrade pip
pip install setuptools

## Install your requirements
pip install -r requirements.txt

