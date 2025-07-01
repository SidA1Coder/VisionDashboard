from flask import Blueprint, render_template, redirect, url_for, request, session

auth_bp = Blueprint('auth', __name__, template_folder='../templates')

@auth_bp.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # IMPORTANT: Replace with a secure way to check credentials
        if username == 'FSROC' and password == 'Rockets1':
            session['logged_in'] = True
            return redirect(url_for('auth.dashboard'))
        else:
            error = 'Invalid Credentials. Please try again.'
            return render_template('login.html', error=error)
    return render_template('login.html')

@auth_bp.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    return render_template('dashboard.html')

@auth_bp.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('auth.login'))