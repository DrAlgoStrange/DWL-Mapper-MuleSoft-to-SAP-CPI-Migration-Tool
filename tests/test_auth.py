import json


def test_register_missing_fields(client):
    res = client.post('/auth/register',
        data=json.dumps({}),
        content_type='application/json')
    assert res.status_code == 400
    data = res.get_json()
    assert data['success'] is False
    assert 'errors' in data


def test_register_invalid_email(client):
    res = client.post('/auth/register',
        data=json.dumps({
            'full_name': 'Test User',
            'project_name': 'Test Project',
            'email': 'test@gmail.com',
            'password': 'TestPass@1',
            'confirm_password': 'TestPass@1'
        }),
        content_type='application/json')
    data = res.get_json()
    assert 'email' in data.get('errors', {})


def test_login_invalid(client):
    res = client.post('/auth/login',
        data=json.dumps({'email': 'nobody@its.jnj.com', 'password': 'wrong'}),
        content_type='application/json')
    assert res.status_code == 401


def test_register_and_login(client):
    payload = {
        'full_name': 'Jane Doe',
        'project_name': 'Migration Q4',
        'email': 'jane.doe@its.jnj.com',
        'wwid': '1234567',
        'password': 'Test@Pass1',
        'confirm_password': 'Test@Pass1'
    }
    res = client.post('/auth/register',
        data=json.dumps(payload),
        content_type='application/json')
    data = res.get_json()
    assert data['success'] is True

    # Duplicate email should fail
    res2 = client.post('/auth/register',
        data=json.dumps(payload),
        content_type='application/json')
    assert res2.status_code == 409
