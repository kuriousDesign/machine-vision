# Create venv using Python 3.13
py -3.13 -m venv venv
# Create venv using Python 3.13 using ubuntu
python3.13 -m venv venv


# Activate venv
venv\Scripts\activate   (this is for windows)
source venv/bin/activate


# Upgrade pip
pip install --upgrade pip

# Install your requirements
pip install -r requirements.txt