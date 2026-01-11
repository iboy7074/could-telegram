from user_manager import UserManager
import json

um = UserManager()
print("--- User Database Dump ---")
print(json.dumps(um.db, indent=2))

admins = [uid for uid, data in um.db.items() if data.get("is_admin")]
if admins:
    print(f"\n✅ Found Admins: {admins}")
else:
    print("\n❌ No Admins found! Did you run '/admin_login secret123' in the bot?")
