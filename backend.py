import requests


def curlThis(url: str):
    response = requests.get(url)

    diddy = response.status_code

    if diddy > 199 or diddy < 299:
        print("Worked")
        print("Status code: " + str(diddy))

        return response.json
