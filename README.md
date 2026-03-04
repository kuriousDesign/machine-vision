
# Dev outside of container
# Install the engine first
sudo apt-get update && sudo apt-get install -y python3-bpfcc bpfcc-tools libbpfcc-dev linux-headers-$(uname -r)



# Create venv using Python 3.13
py -3.13 -m venv venv
# Create venv using Python 3.13 using ubuntu
python3.13 -m venv venv


# Activate venv
source venv/bin/activate
venv\Scripts\activate   (this is for windows)


# Upgrade pip
pip install --upgrade pip

# Install your requirements
pip install -r requirements.txt