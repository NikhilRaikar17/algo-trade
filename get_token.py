from auth import get_login_url, generate_access_token
from kite_client import kite

# Step 1: Get login URL and open it in browser
print("Login here:", get_login_url())

# Step 2: After logging in, copy request_token from the redirect URL
request_token = input("Paste the request_token from URL: ").strip()

# Step 3: Generate and save access token to .env
access_token = generate_access_token(request_token)
kite.set_access_token(access_token)
print("Access token saved:", access_token)
