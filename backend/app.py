from flask import Flask, request, render_template, redirect, url_for, session, send_from_directory, jsonify
from flask_paginate import Pagination, get_page_args
from databases import SQLiteDatabase
from flask_jwt_extended import *
import pathlib, hashlib, datetime
from get_data import get_data_app
import requests
import sys
import json
import os
import uuid
from flask_cors import CORS

database = SQLiteDatabase(f"{str(pathlib.Path(__file__).parent.resolve())}/database.db")
app = Flask(__name__, template_folder="templates")
CORS(app)
app.secret_key = 'all_russia'
app.config['JWT_SECRET_KEY'] = app.secret_key
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_COOKIE_CSRF_PROTECT'] = False
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = datetime.timedelta(weeks=2)
jwt = JWTManager(app)
app.register_blueprint(get_data_app)
SMARTCAPTCHA_SERVER_KEY = os.getenv('SMARTCAPTCHA_SERVER_KEY')
SMARTCAPTCHA_CLIENT_KEY = os.getenv('SMARTCAPTCHA_CLIENT_KEY')

# путь к изображениям
UPLOAD_FOLDER = str(pathlib.Path(__file__).parent.resolve()) + "/public"

table_names = {
    'partners': 'Partners',
    'contacts': 'Contacts',
    'users': 'Users',
    'news': 'News',
}


@jwt.expired_token_loader
@jwt.invalid_token_loader
@jwt.needs_fresh_token_loader
@jwt.unauthorized_loader
def expired_token(*args):
    resp = redirect(url_for("admin_login"))
    unset_jwt_cookies(resp)
    return resp


# вроде как пока не нужно и не функционирует

# @app.route("/data_news")
# def data_news():
#     return json.dumps(database.get_all_posts_news())
#
#
# @app.route("/data_contacts")
# def data_contacts():
#     return json.dumps(database.get_contacts_info())
#
#
# @app.route("/data_main_page")
# def data_main_page():
#     return json.dumps(database.get_main_page_news())
#
#
# @app.route("/data_articles")
# def data_articles():
#     return json.dumps(database.get_all_posts_articles())
#
#
# @app.route("/data_partners")
# def data_partners():
#     return json.dumps(database.get_all_partners())
#
#
# @app.route('/add', methods=['POST'])
# def add():
#     data = request.json
#     url = data['url']
#     title = data['title']
#     subtitle = data['subtitle']
#     tag = data['tag']
#     database.add_post(url, title, subtitle, tag)
#     return data


# маршрут страницы формы для входа в админ-панель
@app.route('/admin_login', methods=['GET', 'POST'])
@jwt_required(optional=True)
def admin_login():
    error = None
    if get_jwt() and get_jwt()["fresh"]:
        return redirect(url_for('admin_panel'))

    if request.method == 'GET':
        # Если GET запрос, показываем форму входа
        return render_template('admin_login.html', captcha_key=SMARTCAPTCHA_CLIENT_KEY, error=error)

    def check_captcha(token):
        resp = requests.get(
            "https://smartcaptcha.yandexcloud.net/validate",
            {
                "secret": SMARTCAPTCHA_SERVER_KEY,
                "token": token
            },
            timeout=1
        )
        server_output = resp.content.decode()
        if resp.status_code != 200:
            print(f"Allow access due to an error: code={resp.status_code}; message={server_output}",
                  file=sys.stderr)
            return True
        return json.loads(server_output)["status"] == "ok"

    token = request.form["smart-token"]

    if check_captcha(token):
        print("Passed")
        # имя пользователя из формы
        username = request.form['username']
        # пароль из формы
        password = request.form['password']
        # шифруем пароль в sha-256
        hashed_password = hashlib.sha256(password.encode('utf-8')).hexdigest()
        # получаем пользователя из БД с таким именем
        user = database.select_one('SELECT * FROM users WHERE username = ?', (username,))

        # проверяем сходятся ли данные формы с данными БД
        if user and user['password'] == hashed_password:
            # в случае успеха создаем токен
            # # и делаем переадресацию пользователя на новую страницу -> в нашу адимнку
            response = redirect(url_for('admin_panel'))
            create_jwt_token(response, user)
            return response
        else:
            error = 'Неправильное имя пользователя или пароль'
    else:
        print("Robot")


def create_jwt_token(resp, user):
    token = create_access_token(identity=user['username'], fresh=True)
    set_access_cookies(resp, token)


@app.route('/admin_panel/', defaults={'table': 'news', 'page': 1, 'sort': 'updated', 'order': 'desc'})
@app.route('/admin_panel/<string:table>', methods=['GET', 'POST'])
@app.route('/admin_panel/<string:table>/<int:page>', methods=['GET', 'POST'])
@app.route('/admin_panel/<string:table>/<int:page>/<string:sort>/<string:order>', methods=['GET', 'POST'])
@jwt_required()
def admin_panel(table, page=1, sort='updated', order='desc'):
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))

    # Параметры пагинации
    per_page = 10
    offset = (page - 1) * per_page

    search_query = request.args.get('search_query', '')

    columns = list(map(lambda x: x[0], database.cursor.execute('SELECT * FROM "{}"'.format(table)).description))

    main_article = None

    order_clause = f"ORDER BY {sort} {order}"
    if search_query:
        total = database.select_one(f'SELECT COUNT(*) FROM "{table}" WHERE title LIKE ?', (f'%{search_query}%',))['COUNT(*)']
        data = database.select_all(f'SELECT * FROM "{table}" WHERE title LIKE ? {order_clause} LIMIT {per_page} OFFSET {offset}', (f'%{search_query}%',))
    else:
        if table == "news":
            total = database.select_one('SELECT COUNT(*) FROM "{}"'.format(table))['COUNT(*)']
            data = database.select_all(f'SELECT * FROM "{table}" {order_clause} LIMIT {per_page} OFFSET {offset}')
            main_article = dict(database.select_one(f'SELECT id FROM main_article'))['id']
        else:
            data = database.select_all('SELECT * FROM "{}"'.format(table))
            return render_template('admin_panel.html', tables=table_names, table=table, columns=columns, data=data)

    # Настройка объекта пагинации
    pagination = Pagination(page=page, per_page=per_page, total=total, record_name='items')

    return render_template('admin_panel.html', tables=table_names, table=table, columns=columns, data=data,
                           main_article=main_article, pagination=pagination, search_query=search_query,
                           sort=sort, order=order, page=page)  # Добавлено page


# маршрут выхода из админ-панели
@app.route('/logout')
def logout():
    resp = redirect(url_for("admin_login"))
    # Удаление данных jwt
    unset_jwt_cookies(resp)
    # Перенаправление на страницу входа
    return resp


@app.route('/admin_panel/delete/<int:id>/<string:table>', methods=['GET', 'POST'])
@jwt_required()
def delete(id, table):
    database.execute('DELETE FROM {} WHERE id =?;'.format(table), (id,))
    print("delete", id, table)
    return redirect(url_for('admin_panel', table=table))


@app.route('/admin_panel/edit/<int:id>/<string:table>', methods=['GET', 'POST'])
@jwt_required()
def edit(id, table):
    if request.method == 'POST':
        # данные из формы
        data = dict(request.form)
        if 'file' in request.files:
            # файл, загруженный в форму
            file = request.files['file']
            if file:
                if verifyExt(file.filename):
                    # Генерация уникального имени файла
                    unique_filename = f"{uuid.uuid4()}_{file.filename}"
                    # сохранение нового файла
                    file.save(pathlib.Path(UPLOAD_FOLDER, unique_filename))
                    try:
                        # удаление старого файла из директории
                        pathlib.Path(UPLOAD_FOLDER, data['url']).unlink()
                    except FileNotFoundError:
                        print("Не удалось найти файл")
                    # запись нового url в словарь
                    data['url'] = unique_filename

        if table == "news":
            # дата и время изменения записи
            data["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Проверяем наличие ключа 'tag' в данных формы
            if 'tag' in data:
                # разбиваем значение поля tag на русский и арабский
                tag_russian, tag_arabian = data["tag"].split("/")
                data["tag"] = tag_russian
                data["tag_arabian"] = tag_arabian

        # Обработка содержимого TinyMCE
        if 'content' in request.form:
            data['content'] = request.form['content']

        query = f"UPDATE {table} SET "
        for key in data.keys():
            query += f"{key} = ?, "
        query = query[:-2]
        query += " WHERE id = ?;"
        values = list(data.values())

        values.append(id)
        database.execute(query, tuple(values))
        return redirect(url_for('admin_panel', table=table))
    else:
        record = database.select_one(f'SELECT * FROM {table} WHERE id=?', (id,))
        columns = record.keys()
        record_dict = dict(record)
        return render_template('edit_record.html', tables=table_names, table=table, id=id, record=record_dict)


@app.route('/admin_panel/add/<string:table>', methods=['GET', 'POST'])
@jwt_required()
def add_record(table):
    if request.method == 'POST':
        data = dict(request.form)
        
        # Обработка изображения, если есть
        if 'file' in request.files:
            file = request.files['file']
            if file and verifyExt(file.filename):
                unique_filename = f"{uuid.uuid4()}_{file.filename}"
                file.save(pathlib.Path(UPLOAD_FOLDER, unique_filename))
                data['url'] = unique_filename  # сохраняем основное изображение
        
        # Обработка содержимого TinyMCE для content
        if 'content' in request.form:
            data['content'] = request.form['content']
        
        # Обработка содержимого TinyMCE для subtitle
        if 'subtitle' in request.form:
            data['subtitle'] = request.form['subtitle']
        
        # Обработка содержимого TinyMCE для subtitle_arabian
        if 'subtitle_arabian' in request.form:
            data['subtitle_arabian'] = request.form['subtitle_arabian']

        # Получаем максимальный ID и увеличиваем его на 1 для новой записи
        last_id = database.select_one(f'SELECT MAX(id) FROM {table}')[0]
        new_id = last_id + 1 if last_id is not None else 1

        # Добавляем ID в данные для вставки в БД
        data['id'] = new_id

        # Формируем запрос SQL для вставки данных
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?' for _ in data.keys()])
        values = list(data.values())

        # Выполняем SQL-запрос для вставки данных в таблицу
        query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        database.execute(query, tuple(values))

        return redirect(url_for('admin_panel', table=table))
    else:
        # Получаем названия колонок таблицы для формирования формы
        columns = [column[1] for column in database.cursor.execute('PRAGMA table_info({})'.format(table)).fetchall()]
        return render_template('add_record.html', tables=table_names, table=table, columns=columns)


@app.route('/admin_panel/make_main/<int:id>', methods=['GET'])
@jwt_required()
def make_main(id):
    if request.method == 'GET':
        database.execute(f'UPDATE main_article SET id={id}')
        return redirect(url_for('admin_panel', table="news"))


# загрузка файла из директории файлов
@app.route('/uploads/<filename>')
@jwt_required()
def send_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# проверка формата изображения
def verifyExt(filename):
    ext = filename.rsplit('.', 1)[1]
    if ext in ['JPEG', 'JPG', 'png', 'jpg', 'PNG']:
        return True
    return False

@app.route('/upload_image', methods=['POST'])
@jwt_required()
def upload_image():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file part'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No selected file'})

    if file and verifyExt(file.filename):
        # Генерация уникального имени файла
        unique_filename = f"{uuid.uuid4()}_{file.filename}"
        # Сохранение нового файла
        file.save(pathlib.Path(UPLOAD_FOLDER, unique_filename))
        # Возвращаем URL загруженного изображения для TinyMCE
        return jsonify({'success': True, 'location': url_for('send_file', filename=unique_filename)})
    else:
        return jsonify({'success': False, 'error': 'Invalid file format'})

# Функция проверки формата изображения
def verifyExt(filename):
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in {'jpg', 'jpeg', 'png'}


print(__name__)
if __name__ == "__main__":
    database.connect()

    app.run(port=5000, debug=True)
