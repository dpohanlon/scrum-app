# Train Car Crowding

This repository contains a small Flask application that visualises live crowding levels for London Underground trains.
It queries Transport for London's crowding API and overlays occupancy estimates onto a carriage diagram.

## Requirements

* Python 3
* A [TfL API key](https://api-portal.tfl.gov.uk) supplied as the `TFL_APP_KEY` env var or a Docker secret named `tfl_app_key`

Install dependencies with:

```
pip install -r requirements.txt
```

## Running locally

```
export TFL_APP_KEY=your_api_key
flask --app app run
```

The app exposes a root page with a simple form and a `/crowding` endpoint returning JSON.

## Docker

### Build and push

```
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com" # e.g. 541738546266.dkr.ecr.us-east-1.amazonaws.com

aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "$REGISTRY"
docker build --platform linux/amd64 -t tfl-flask .
docker tag tfl-flask:latest "$REGISTRY/tfl-flask:latest"
docker push "$REGISTRY/tfl-flask:latest"
```

### Running with a Docker secret

```
echo "your_api_key" | docker secret create tfl_app_key -
docker service create --name tfl-app --secret tfl_app_key -p 8080:8080 "$REGISTRY/tfl-flask:latest"
```

## License

Released under the MIT License. See `LICENSE` for details.
