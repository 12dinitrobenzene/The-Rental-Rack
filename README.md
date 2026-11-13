# is2108-clothing-store

## Master administrator setup

The master administrator is a Django superuser. Create the account after
applying the database migrations:

```bash
python manage.py migrate
python manage.py createsuperuser
```

Start the development server and sign in through the website's shared login
page at `http://127.0.0.1:8000/accounts/login/` using the credentials entered
above:

```bash
python manage.py runserver
```

The master account is redirected to the Platform Admin Homepage. It can use
**Create admin** and **Manage admins** to create, edit, deactivate and
reactivate ordinary platform-admin accounts. Ordinary platform admins sign in
through the same shared login page but cannot manage other admin accounts.
