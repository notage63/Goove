# Goove

Small Python utility that periodically reads values from a Govee sensor through the
Govee Cloud API.

## Requirements
- Python 3.9+
- `pip install -r requirements.txt`

## Configuration
Settings are read from environment variables — see `.env.example` for the available
options. For local use, copy it to `.env` and fill in your own values.

## Usage
```
python scripts/poll_govee.py --list-devices   # show devices on the account
python scripts/poll_govee.py --once            # take a single reading
```
