from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from datetime import datetime, timedelta  # Add timedelta to imports


app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Database connection
def get_db_connection():
    return psycopg2.connect(
        dbname='movie_db',
        user='postgres',
        password='Adithya@999',
        host='localhost'
    )

# Dynamic pricing calculation
def calculate_price(base_price, start_time):
    hour = start_time.hour
    # Convert Decimal to float for calculation
    base_price_float = float(base_price)
    
    # Simple dynamic pricing: peak hours (6pm-11pm) have 50% higher prices
    if 18 <= hour <= 23:
        return round(base_price_float * 1.5, 2)
    return round(base_price_float, 2)

# Routes
@app.route('/')
def home():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM movies ORDER BY release_date DESC')
    movies = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', movies=movies)

@app.route('/shows/<int:movie_id>')
def movie_shows(movie_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get movie details
    cur.execute('SELECT * FROM movies WHERE movie_id = %s', (movie_id,))
    movie = cur.fetchone()
    
    # Get shows with dynamic pricing
    cur.execute('''
        SELECT s.show_id, a.name, s.start_time, s.end_time, s.base_price 
        FROM shows s
        JOIN auditoriums a ON s.auditorium_id = a.auditorium_id
        WHERE s.movie_id = %s
    ''', (movie_id,))
    
    shows = []
    for show in cur.fetchall():
        show_id, auditorium, start_time, end_time, base_price = show
        price = calculate_price(base_price, start_time)
        shows.append({
            'id': show_id,
            'auditorium': auditorium,
            'start_time': start_time,
            'price': price
        })
    
    cur.close()
    conn.close()
    return render_template('shows.html', movie=movie, shows=shows)

@app.route('/book/<int:show_id>', methods=['GET', 'POST'])
def book_tickets(show_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        if request.method == 'POST':
            # Get seat IDs as integers
            seat_ids = list(map(int, request.form.getlist('seats')))
            
            if not seat_ids:
                flash('No seats selected!', 'danger')
                return redirect(url_for('book_tickets', show_id=show_id))
            
            user_id = session['user_id']
            
            # Check seat availability
            cur.execute('''
                SELECT seat_id FROM booking_seats
                WHERE seat_id IN %s
                AND booking_id IN (
                    SELECT booking_id FROM bookings WHERE show_id = %s
                )
            ''', (tuple(seat_ids), show_id))
            
            if cur.fetchone():
                flash('Some seats are already booked!', 'danger')
                return redirect(url_for('book_tickets', show_id=show_id))
            
            # Get show price
            cur.execute('SELECT base_price FROM shows WHERE show_id = %s', (show_id,))
            base_price = cur.fetchone()[0]
            total_price = float(base_price) * len(seat_ids)
            
            # Create booking
            cur.execute('''
                INSERT INTO bookings (show_id, user_id, total_price)
                VALUES (%s, %s, %s)
                RETURNING booking_id
            ''', (show_id, user_id, total_price))
            booking_id = cur.fetchone()[0]
            
            # Insert booked seats
            for seat_id in seat_ids:
                cur.execute('''
                    INSERT INTO booking_seats (booking_id, seat_id)
                    VALUES (%s, %s)
                ''', (booking_id, seat_id))
            
            conn.commit()
            flash('Booking successful!', 'success')
            return redirect(url_for('booking_confirmation', booking_id=booking_id))
        
        # GET: Show available seats
        cur.execute('''
            SELECT s.seat_id, s.row_num, s.seat_num 
            FROM seats s
            WHERE s.auditorium_id = (
                SELECT auditorium_id FROM shows WHERE show_id = %s
            )
            AND s.seat_id NOT IN (
                SELECT seat_id FROM booking_seats
                WHERE booking_id IN (
                    SELECT booking_id FROM bookings WHERE show_id = %s
                )
            )
        ''', (show_id, show_id))
        
        available_seats = cur.fetchall()
        return render_template('booking.html', 
                             seats=available_seats, 
                             show_id=show_id)
    
    except Exception as e:
        conn.rollback()
        flash(f'Booking failed: {str(e)}', 'danger')
        return redirect(url_for('home'))
    
    finally:
        cur.close()
        conn.close()

@app.route('/booking/<int:booking_id>')
def booking_confirmation(booking_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute('''
        SELECT m.title, a.name, s.start_time, b.total_price 
        FROM bookings b
        JOIN shows s ON b.show_id = s.show_id
        JOIN movies m ON s.movie_id = m.movie_id
        JOIN auditoriums a ON s.auditorium_id = a.auditorium_id
        WHERE b.booking_id = %s
    ''', (booking_id,))
    
    booking_info = cur.fetchone()
    cur.close()
    conn.close()
    
    return render_template('booking_confirmation.html', booking_info=booking_info)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM users WHERE email = %s', (request.form['email'],))
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if user and user[2] == request.form['password']:
            session.update({
                'user_id': user[0],
                'user_role': user[3],
                'email': user[1]
            })
            # Redirect based on role
            if user[3] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user[3] == 'staff':
                return redirect(url_for('staff_dashboard'))
            else:
                return redirect(url_for('home'))
        flash('Invalid credentials')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            # Check if user exists
            cur.execute('SELECT * FROM users WHERE email = %s', (email,))
            if cur.fetchone():
                flash('Email already exists')
                return redirect(url_for('register'))
            
            # Insert new user (plain text password)
            cur.execute('''
                INSERT INTO users (email, password_hash, role)
                VALUES (%s, %s, 'customer')
            ''', (email, password))
            conn.commit()
            flash('Registration successful! Please login')
            return redirect(url_for('login'))
            
        except Exception as e:
            conn.rollback()
            flash('Registration failed')
        finally:
            cur.close()
            conn.close()
            
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# =================================================================
# Admin routes
# =================================================================

def validate_admin():
    return session.get('user_role') == 'admin'

def calculate_slots(date):
    base_date = datetime.strptime(date, "%Y-%m-%d")
    return {
        1: (base_date.replace(hour=6), base_date.replace(hour=9)),
        2: (base_date.replace(hour=9), base_date.replace(hour=12)),
        3: (base_date.replace(hour=12), base_date.replace(hour=15)),
        4: (base_date.replace(hour=15), base_date.replace(hour=18)),
        5: (base_date.replace(hour=18), base_date.replace(hour=21)),
        6: (base_date.replace(hour=21), base_date.replace(hour=0) + timedelta(days=1))
    }

@app.route('/admin')
def admin_dashboard():
    if not validate_admin():
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get movie statistics
    cur.execute('''
        SELECT m.movie_id, m.title, 
               COUNT(b.booking_id) AS bookings,
               COALESCE(SUM(b.total_price), 0) AS revenue
        FROM movies m
        LEFT JOIN shows s ON m.movie_id = s.movie_id
        LEFT JOIN bookings b ON s.show_id = b.show_id
        GROUP BY m.movie_id
    ''')
    stats = cur.fetchall()
    
    # Get recent bookings
    cur.execute('''
        SELECT b.booking_id, m.title, a.name, b.total_price, b.booking_time 
        FROM bookings b
        JOIN shows s ON b.show_id = s.show_id
        JOIN movies m ON s.movie_id = m.movie_id
        JOIN auditoriums a ON s.auditorium_id = a.auditorium_id
        ORDER BY b.booking_time DESC LIMIT 10
    ''')
    recent_bookings = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('admin/dashboard.html', 
                         stats=stats,
                         recent_bookings=recent_bookings)

@app.route('/admin/movies', methods=['GET', 'POST'])
def admin_movies():
    if not validate_admin():
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        # Handle delete action
        if 'delete_id' in request.form:
            movie_id = request.form['delete_id']
            try:
                cur.execute('DELETE FROM movies WHERE movie_id = %s', (movie_id,))
                conn.commit()
                flash('Movie deleted successfully', 'success')
            except Exception as e:
                conn.rollback()
                flash(f'Error deleting movie: {str(e)}', 'danger')
        # Handle add action        
        else:
            try:
                cur.execute('''
                    INSERT INTO movies (title, duration, genre, language, release_date)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (request.form['title'],
                     request.form['duration'],
                     request.form['genre'],
                     request.form['language'],
                     request.form['release_date']))
                conn.commit()
                flash('Movie added successfully', 'success')
            except Exception as e:
                conn.rollback()
                flash(f'Error adding movie: {str(e)}', 'danger')
    
    cur.execute('SELECT * FROM movies ORDER BY release_date DESC')
    movies = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('admin/movies.html', movies=movies)

@app.route('/admin/movies/<int:movie_id>')
def admin_movie_detail(movie_id):
    if not validate_admin(): return redirect(url_for('login'))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM movies WHERE movie_id = %s', (movie_id,))
    movie = cur.fetchone()
    # Booked seats
    cur.execute('''
        SELECT b.booking_id, s.seat_id, a.name, sh.start_time, u.email
        FROM bookings b
        JOIN booking_seats bs ON b.booking_id = bs.booking_id
        JOIN seats s ON bs.seat_id = s.seat_id
        JOIN shows sh ON b.show_id = sh.show_id
        JOIN auditoriums a ON sh.auditorium_id = a.auditorium_id
        JOIN users u ON b.user_id = u.user_id
        WHERE sh.movie_id = %s
    ''', (movie_id,))
    bookings = cur.fetchall()
    # Available seats
    cur.execute('''
        SELECT s.seat_id 
        FROM seats s
        WHERE s.auditorium_id IN (
            SELECT auditorium_id FROM shows WHERE movie_id = %s
        )
        AND s.seat_id NOT IN (
            SELECT seat_id FROM booking_seats
        )
    ''', (movie_id,))
    available_seats = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return render_template('admin/movie_detail.html', movie=movie, bookings=bookings, available_seats=available_seats)

@app.route('/admin/screens', methods=['GET', 'POST'])
def admin_screens():
    if not validate_admin(): return redirect(url_for('login'))
    if request.method == 'POST':
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute('''
                INSERT INTO auditoriums (name, total_seats)
                VALUES (%s, %s)
                RETURNING auditorium_id
            ''', (request.form['name'], int(request.form['rows'])*int(request.form['seats_per_row'])))
            auditorium_id = cur.fetchone()[0]
            for row in range(1, int(request.form['rows'])+1):
                for seat in range(1, int(request.form['seats_per_row'])+1):
                    cur.execute('''
                        INSERT INTO seats (auditorium_id, row_num, seat_num)
                        VALUES (%s, %s, %s)
                    ''', (auditorium_id, row, seat))
            conn.commit()
            flash('Screen created successfully')
        except Exception as e:
            conn.rollback()
            flash(f'Error: {str(e)}')
        finally:
            cur.close()
            conn.close()
    return render_template('admin/screens.html')

@app.route('/admin/shows/new', methods=['GET', 'POST'])
def admin_add_show():
    if not validate_admin(): return redirect(url_for('login'))
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == 'POST':
        try:
            slot_data = calculate_slots(request.form['date'])[int(request.form['slot'])]
            cur.execute('''
                INSERT INTO shows 
                (movie_id, auditorium_id, start_time, end_time, base_price, slot)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (request.form['movie_id'], request.form['auditorium_id'],
                 slot_data[0], slot_data[1], request.form['base_price'], request.form['slot']))
            conn.commit()
            flash('Show added successfully')
        except Exception as e:
            conn.rollback()
            flash(f'Error: {str(e)}')
    cur.execute('SELECT movie_id, title FROM movies')
    movies = cur.fetchall()
    cur.execute('SELECT auditorium_id, name FROM auditoriums')
    auditoriums = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin/new_show.html', movies=movies, auditoriums=auditoriums, slots=range(1,7))

@app.route('/admin/shows')
def admin_shows():
    if not validate_admin():
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute('''
        SELECT s.show_id, m.title, a.name, 
               s.start_time, s.end_time, s.base_price
        FROM shows s
        JOIN movies m ON s.movie_id = m.movie_id
        JOIN auditoriums a ON s.auditorium_id = a.auditorium_id
        ORDER BY s.start_time DESC
    ''')
    shows = cur.fetchall()
    
    cur.close()
    conn.close()
    return render_template('admin/shows.html', shows=shows)

@app.route('/admin/shows/delete/<int:show_id>', methods=['POST'])
def admin_delete_show(show_id):
    if not validate_admin():
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('DELETE FROM shows WHERE show_id = %s', (show_id,))
        conn.commit()
        flash('Show deleted successfully', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting show: {str(e)}', 'danger')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('admin_shows'))

# ========================
#      Staff Routes
# ========================
def validate_staff():
    return 'user_id' in session and session.get('user_role') in ['admin', 'staff']

@app.route('/staff')
def staff_dashboard():
    if not validate_staff():
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute('''
        SELECT m.movie_id, m.title, 
               COUNT(DISTINCT s.show_id) AS screenings,
               COUNT(b.booking_id) AS bookings,
               ARRAY_AGG(DISTINCT a.name) AS screens
        FROM movies m
        LEFT JOIN shows s ON m.movie_id = s.movie_id
        LEFT JOIN auditoriums a ON s.auditorium_id = a.auditorium_id
        LEFT JOIN bookings b ON s.show_id = b.show_id
        GROUP BY m.movie_id
        ORDER BY m.title
    ''')
    movies = cur.fetchall()
    
    cur.close()
    conn.close()
    return render_template('staff/dashboard.html', movies=movies)

@app.route('/staff/movies/<int:movie_id>')
def staff_movie_detail(movie_id):
    if not validate_staff():
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Get movie details
    cur.execute('SELECT * FROM movies WHERE movie_id = %s', (movie_id,))
    movie = cur.fetchone()
    
    # Get shows with bookings
    cur.execute('''
        SELECT s.show_id, a.name, s.start_time, s.end_time, s.slot,
               COUNT(b.booking_id) AS total_bookings
        FROM shows s
        JOIN auditoriums a ON s.auditorium_id = a.auditorium_id
        LEFT JOIN bookings b ON s.show_id = b.show_id
        WHERE s.movie_id = %s
        GROUP BY s.show_id, a.name
        ORDER BY s.start_time
    ''', (movie_id,))
    shows = cur.fetchall()
    
    # Get detailed bookings
    show_bookings = []
    for show in shows:
        cur.execute('''
            SELECT b.booking_id, u.email, 
                   ARRAY_AGG(s.row_num || '-' || s.seat_num) AS seats,
                   b.total_price, b.booking_time
            FROM bookings b
            JOIN booking_seats bs ON b.booking_id = bs.booking_id
            JOIN seats s ON bs.seat_id = s.seat_id
            JOIN users u ON b.user_id = u.user_id
            WHERE b.show_id = %s
            GROUP BY b.booking_id, u.email
        ''', (show[0],))
        bookings = cur.fetchall()
        show_bookings.append({
            'show_info': show,
            'bookings': bookings
        })
    
    cur.close()
    conn.close()
    
    return render_template('staff/movie_detail.html', 
                         movie=movie,
                         show_bookings=show_bookings)

if __name__ == '__main__':
    app.run(debug=True)
