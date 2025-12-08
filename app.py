import os
from datetime import datetime
from pathlib import Path
from functools import wraps
from uuid import uuid4
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///appointments.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "dev-secret-key"
app.config["UPLOAD_FOLDER"] = Path("static/uploads")

db = SQLAlchemy(app)


class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(80), nullable=False)
    room = db.Column(db.String(10), nullable=False)
    photo_url = db.Column(db.String(255), nullable=True)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"))

    teacher = db.relationship("Teacher")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False)
    time_label = db.Column(db.String(40), nullable=False)
    parent_name = db.Column(db.String(120))
    parent_email = db.Column(db.String(120))
    question = db.Column(db.Text)
    booked = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    teacher = db.relationship("Teacher", backref="slots")

    __table_args__ = (UniqueConstraint("teacher_id", "time_label", name="uq_teacher_time"),)


def seed_data():
    upload_folder: Path = app.config["UPLOAD_FOLDER"]
    upload_folder.mkdir(parents=True, exist_ok=True)
    if Teacher.query.count() == 0:
        teachers = [
            Teacher(
                full_name="Ирина Сергеевна Громова",
                subject="Математика",
                room="201",
                photo_url="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=300&q=80&sig=11",
            ),
            Teacher(
                full_name="Дмитрий Павлович Соколов",
                subject="Физика",
                room="305",
                photo_url="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=300&q=80&sig=22",
            ),
            Teacher(
                full_name="Анна Викторовна Ковалёва",
                subject="Литература",
                room="118",
                photo_url="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=300&q=80&sig=33",
            ),
            Teacher(
                full_name="Сергей Николаевич Белов",
                subject="История",
                room="214",
                photo_url="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=300&q=80&sig=44",
            ),
            Teacher(
                full_name="Мария Алексеевна Пирогова",
                subject="Биология",
                room="409",
                photo_url="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=300&q=80&sig=55",
            ),
        ]
        db.session.bulk_save_objects(teachers)
        db.session.commit()

    def ensure_user(email: str, role: str, password: str, teacher_id=None):
        user = User.query.filter_by(email=email).first()
        if user:
            return
        user = User(email=email, role=role, teacher_id=teacher_id)
        user.set_password(password)
        db.session.add(user)

    ensure_user("admin@school.local", "admin", "admin123")
    ensure_user("parent@example.com", "parent", "parent123")
    for teacher in Teacher.query.all():
        ensure_user(f"{teacher.id}@school.local", "teacher", "teacher123", teacher_id=teacher.id)
    db.session.commit()

    default_times = ["09:00", "09:30", "10:00", "10:30", "11:00", "14:00", "14:30"]
    for teacher in Teacher.query.all():
        existing_times = {slot.time_label for slot in teacher.slots}
        for time_label in default_times:
            if time_label not in existing_times:
                db.session.add(Slot(teacher_id=teacher.id, time_label=time_label))
    db.session.commit()


def setup():
    db.create_all()
    seed_data()


@app.before_request
def ensure_db():
    if not hasattr(app, "_db_inited"):
        setup()
        app._db_inited = True


@app.route("/")
def index():
    return render_template("index.html")


def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = session.get("user_id")
            if not user_id:
                flash("Пожалуйста, войдите в аккаунт.", "error")
                return redirect(url_for("login"))

            user = User.query.get(user_id)
            if not user:
                session.clear()
                flash("Сессия устарела. Войдите снова.", "error")
                return redirect(url_for("login"))

            allowed = {role} if isinstance(role, str) else set(role) if role else None
            if allowed and user.role not in allowed:
                flash("Недостаточно прав для доступа.", "error")
                return redirect(url_for("index"))

            return fn(*args, **kwargs)

        return wrapper

    return decorator


def save_photo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    filename = secure_filename(file_storage.filename)
    if not filename:
        return None
    ext = Path(filename).suffix
    new_name = f"{uuid4().hex}{ext}"
    upload_folder: Path = app.config["UPLOAD_FOLDER"]
    upload_folder.mkdir(parents=True, exist_ok=True)
    path = upload_folder / new_name
    file_storage.save(path)
    return f"uploads/{new_name}"


@app.context_processor
def inject_user():
    user_id = session.get("user_id")
    user = User.query.get(user_id) if user_id else None
    return {"current_user": user}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Неверный email или пароль.", "error")
            return redirect(url_for("login"))

        session["user_id"] = user.id
        session["role"] = user.role

        if user.role == "teacher":
            return redirect(url_for("teacher_dashboard"))
        if user.role == "admin":
            return redirect(url_for("admin_users"))
        return redirect(url_for("parent"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из аккаунта.", "success")
    return redirect(url_for("index"))


@app.route("/parent")
@login_required(role="parent")
def parent():
    teachers = Teacher.query.all()
    return render_template("parent_teachers.html", teachers=teachers)


@app.route("/parent/teacher/<int:teacher_id>", methods=["GET"])
@login_required(role="parent")
def parent_teacher(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    slots = Slot.query.filter_by(teacher_id=teacher_id).order_by(Slot.time_label).all()
    return render_template("teacher_booking.html", teacher=teacher, slots=slots)


@app.route("/book/<int:slot_id>", methods=["POST"])
@login_required(role="parent")
def book_slot(slot_id):
    slot = Slot.query.get_or_404(slot_id)
    if slot.booked:
        flash("Это время уже занято. Пожалуйста, выберите другое.", "error")
        return redirect(url_for("parent_teacher", teacher_id=slot.teacher_id))

    parent_name = request.form.get("parent_name", "").strip()
    parent_email = request.form.get("parent_email", "").strip()
    question = request.form.get("question", "").strip()

    if not parent_name or not parent_email:
        flash("Пожалуйста, заполните имя и электронную почту.", "error")
        return redirect(url_for("parent_teacher", teacher_id=slot.teacher_id))

    slot.parent_name = parent_name
    slot.parent_email = parent_email
    slot.question = question
    slot.booked = True
    slot.created_at = datetime.utcnow()
    db.session.commit()

    flash("Запись подтверждена! До встречи в школе.", "success")
    return redirect(url_for("parent_teacher", teacher_id=slot.teacher_id))


@app.route("/teacher")
@login_required(role="teacher")
def teacher_dashboard():
    user = User.query.get_or_404(session["user_id"])
    if not user.teacher_id:
        flash("Учетная запись преподавателя не привязана к расписанию.", "error")
        return redirect(url_for("index"))

    teacher = Teacher.query.get_or_404(user.teacher_id)
    slots = Slot.query.filter_by(teacher_id=user.teacher_id).order_by(Slot.time_label).all()

    return render_template("teacher_dashboard.html", teacher=teacher, slots=slots)


@app.route("/admin/users", methods=["GET", "POST"])
@login_required(role="admin")
def admin_users():
    teachers = Teacher.query.all()

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        role = request.form.get("role")
        teacher_id = request.form.get("teacher_id", type=int)
        photo_file = request.files.get("photo_file")

        if not email or not password or role not in {"parent", "teacher", "admin"}:
            flash("Заполните email, пароль и роль корректно.", "error")
            return redirect(url_for("admin_users"))

        if User.query.filter_by(email=email).first():
            flash("Пользователь с таким email уже существует.", "error")
            return redirect(url_for("admin_users"))

        new_user = User(email=email, role=role)
        new_user.set_password(password)
        if role == "teacher":
            if not teacher_id:
                flash("Для роли преподаватель выберите преподавателя.", "error")
                return redirect(url_for("admin_users"))
            teacher = Teacher.query.get_or_404(teacher_id)
            new_user.teacher_id = teacher_id
            saved_path = save_photo(photo_file)
            if saved_path:
                teacher.photo_url = saved_path

        db.session.add(new_user)
        db.session.commit()
        flash("Учетная запись создана.", "success")
        return redirect(url_for("admin_users"))

    users = User.query.order_by(User.role, User.email).all()
    return render_template("admin_users.html", users=users, teachers=teachers)


@app.route("/admin/users/<int:user_id>", methods=["POST"])
@login_required(role="admin")
def admin_update_user(user_id):
    user = User.query.get_or_404(user_id)
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    role = request.form.get("role")
    teacher_id = request.form.get("teacher_id", type=int)
    photo_file = request.files.get("photo_file")

    if not email or role not in {"parent", "teacher", "admin"}:
        flash("Неверные данные.", "error")
        return redirect(url_for("admin_users"))

    existing = User.query.filter(User.email == email, User.id != user.id).first()
    if existing:
        flash("Email уже используется другим пользователем.", "error")
        return redirect(url_for("admin_users"))

    user.email = email
    user.role = role
    if role == "teacher":
        if not teacher_id:
            flash("Для роли преподаватель выберите преподавателя.", "error")
            return redirect(url_for("admin_users"))
        teacher = Teacher.query.get_or_404(teacher_id)
        user.teacher_id = teacher_id
        saved_path = save_photo(photo_file)
        if saved_path:
            teacher.photo_url = saved_path
    else:
        user.teacher_id = None
    if password:
        user.set_password(password)

    db.session.commit()
    flash("Учетная запись обновлена.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required(role="admin")
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.email == "admin@school.local":
        flash("Нельзя удалить базового администратора.", "error")
        return redirect(url_for("admin_users"))
    db.session.delete(user)
    db.session.commit()
    flash("Пользователь удален.", "success")
    return redirect(url_for("admin_users"))


if __name__ == "__main__":
    with app.app_context():
        setup()
    app.run(debug=True)
