import hashlib
import webbrowser
from secrets import API_KEY, SHARED_SECRET

import requests


def get_signature(params, secret):
    """
    Last.fm requires a custom md5 hash of all parameters sorted alphabetically,
    concatenated together, and ending with your shared secret.
    """
    sorted_keys = sorted(params.keys())
    sig_string = "".join(f"{k}{params[k]}" for k in sorted_keys if k != "format")
    sig_string += secret
    return hashlib.md5(sig_string.encode("utf-8")).hexdigest()


def main():
    # 1. Fetch an unauthorized request token
    res = requests.get(
        "https://ws.audioscrobbler.com/2.0/",
        params={"method": "auth.getToken", "api_key": API_KEY, "format": "json"},
    ).json()
    token = res.get("token")
    if not token:
        print(f"Failed to get token: {res}")
        return

    # 2. Open the user authorization page in your browser
    auth_url = f"http://www.last.fm/api/auth/?api_key={API_KEY}&token={token}"
    print(f"Opening browser to authorize: {auth_url}")
    webbrowser.open(auth_url)
    input("Press Enter AFTER you click 'Allow Access' in your browser...")

    # 3. Exchange the authorized token for a permanent session key
    params = {
        "method": "auth.getSession",
        "api_key": API_KEY,
        "token": token,
    }
    params["api_sig"] = get_signature(params, SHARED_SECRET)
    params["format"] = "json"

    res = requests.get("https://ws.audioscrobbler.com/2.0/", params=params).json()

    session = res.get("session")
    if session:
        print("\n--- SUCCESS! ---")
        print(f"Username: {session['name']}")
        print(f"Permanent Session Key: {session['key']}")
        print("Save this session key in your upload script!\n")
    else:
        print(f"Error obtaining session: {res}")


if __name__ == "__main__":
    main()
