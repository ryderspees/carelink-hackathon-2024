# Create a virtual environment
python -m venv env

# Activate virtual environment
.\env\Scripts\Activate.ps1

# Install packages
pip install -r requirements.txt

# Download the spaCy model
python -m spacy download en_core_web_trf