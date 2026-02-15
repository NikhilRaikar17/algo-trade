from auth import generate_access_token

# Step 1: Ask user to log in
print("🔐 Opening login URL...")
access_token = generate_access_token()

# Step 2: Confirm success
print("✅ Access token generated and saved to .env")
