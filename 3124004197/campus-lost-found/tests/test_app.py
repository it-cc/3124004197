from datetime import date
import io
import json
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from campus_app.main import create_app
from campus_app import ai
from campus_app.matching import validate_ai_matches


@pytest.fixture
def app(tmp_path, monkeypatch):
    app=create_app(tmp_path,demo=False)
    def no_ai(*args):raise ai.AIError('测试未配置 AI')
    monkeypatch.setattr(ai,'rank_matches',no_ai)
    monkeypatch.setattr(ai,'chat_reply',lambda item,history,question:'测试回答')
    return app


def account(client, name):
    r=client.post('/api/auth/register',json={'username':name,'password':'password123','nickname':name,'contact':'private-'+name})
    assert r.status_code==200,r.text
    return r.json()['id']


def item(client, kind='found', title='蓝色保温杯', hint='hidden-mark'):
    r=client.post('/api/items',data={'kind':kind,'title':title,'category':'其他','description':'蓝色杯身白色盖子小猫贴纸','location':'图书馆二楼','occurred_on':date.today().isoformat(),'verification_hint':hint})
    assert r.status_code==200,r.text
    return r.json()['id']


def test_publish_auth_and_private_fields(app):
    with TestClient(app) as client:
        assert client.post('/api/items',data={}).status_code==401
        account(client,'poster')
        ident=item(client)
        own=client.get('/api/items/'+str(ident)).json()
        assert own['verification_hint']=='hidden-mark'
        assert 'private-poster' not in json.dumps(own)
        assert 'hidden-mark' not in json.dumps(client.get('/api/items').json())
        client.post('/api/auth/logout')
        public=client.get('/api/items/'+str(ident)).json()
        assert 'verification_hint' not in public
        assert 'contact' not in public
        assert client.get('/api/auth/me').status_code==401
        assert client.post('/api/auth/login',json={'username':'poster','password':'bad'}).status_code==401
        assert client.post('/api/auth/login',json={'username':'poster','password':'password123'}).status_code==200


def test_claim_review_and_contact_visibility(app):
    with TestClient(app) as poster,TestClient(app) as claimant,TestClient(app) as stranger:
        account(poster,'owner');account(claimant,'claimant');account(stranger,'stranger')
        ident=item(poster)
        r=claimant.post(f'/api/items/{ident}/claims',json={'proof':'杯子底部有我的名字刻字'})
        assert r.status_code==200,r.text
        claim=r.json()['id']
        assert 'contact' not in claimant.get('/api/me/claims').json()['claims'][0]
        assert stranger.get('/api/me/claims').json()['claims']==[]
        assert stranger.post(f'/api/claims/{claim}/decision',json={'decision':'accept'}).status_code==403
        assert claimant.patch(f'/api/items/{ident}',json={}).status_code in (403,422)
        assert poster.delete(f'/api/items/{ident}').status_code==409
        assert poster.post(f'/api/claims/{claim}/decision',json={'decision':'accept'}).status_code==200
        assert claimant.get('/api/me/claims').json()['claims'][0]['contact']=='private-owner'
        assert poster.get('/api/me/claims').json()['claims'][0]['contact']=='private-claimant'
        assert poster.get(f'/api/items/{ident}').json()['status']=='returned'
        assert stranger.post(f'/api/items/{ident}/claims',json={'proof':'新的描述必须能证明所有权'}).status_code==409
        assert poster.post(f'/api/claims/{claim}/decision',json={'decision':'reject'}).status_code==409


def test_reject_does_not_share_contact_and_duplicates_blocked(app):
    with TestClient(app) as a,TestClient(app) as b:
        account(a,'aaa');account(b,'bbb');ident=item(a)
        claim=b.post(f'/api/items/{ident}/claims',json={'proof':'这份描述是用于核验的线索'}).json()['id']
        assert b.post(f'/api/items/{ident}/claims',json={'proof':'第二次重复认领的说明内容'}).status_code==409
        assert a.post(f'/api/claims/{claim}/decision',json={'decision':'reject'}).status_code==200
        assert 'contact' not in b.get('/api/me/claims').json()['claims'][0]
        assert a.get(f'/api/items/{ident}').json()['status']=='active'


def test_photo_is_decoded_and_reencoded(app):
    with TestClient(app) as c:
        account(c,'photo_user')
        data={'kind':'lost','title':'蓝色水杯','category':'其他','description':'蓝色水杯有猫贴纸','location':'图书馆二楼','occurred_on':date.today().isoformat()}
        assert c.post('/api/items',data=data,files={'photo':('bad.svg',b'<svg/>','image/svg+xml')}).status_code==422
        image=io.BytesIO();Image.new('RGB',(100,100),'blue').save(image,'PNG')
        r=c.post('/api/items',data=data,files={'photo':('real.png',image.getvalue(),'image/png')})
        assert r.status_code==200,r.text
        url=c.get('/api/items/'+str(r.json()['id'])).json()['photo_url']
        result=c.get(url)
        assert result.status_code==200 and result.content.startswith(b'\xff\xd8')


def test_rules_fallback_and_ai_whitelist(app,monkeypatch):
    with TestClient(app) as a,TestClient(app) as b:
        account(a,'lost_user');account(b,'found_user')
        target=item(a,'lost');candidate=item(b)
        result=a.post(f'/api/items/{target}/matches').json()
        assert result['method']=='rules' and result['matches'][0]['item']['id']==candidate
        def rank(target,candidates):
            assert 'verification_hint' not in json.dumps(target)
            assert 'hidden-mark' not in json.dumps(candidates)
            assert 'private-' not in json.dumps(candidates)
            return {'matches':[{'id':999999,'score':100},{'id':candidate,'score':95,'reasons':['公开描述接近'],'questions':['核对刻字']} ]}
        monkeypatch.setattr(ai,'rank_matches',rank)
        result=a.post(f'/api/items/{target}/matches').json()
        assert result['method']=='deepseek' and len(result['matches'])==1
        assert result['matches'][0]['item']['id']==candidate


def test_chat_history_is_private_and_keeps_turns(app,monkeypatch):
    calls=[]
    def chat(item,history,question):calls.append((item,history,question));return '回复 '+question
    monkeypatch.setattr(ai,'chat_reply',chat)
    with TestClient(app) as a,TestClient(app) as b:
        account(a,'chat_a');account(b,'chat_b');ident=item(a)
        assert a.post(f'/api/items/{ident}/chat',json={'message':'怎么找线索？'}).status_code==200
        assert a.post(f'/api/items/{ident}/chat',json={'message':'继续上一个问题'}).status_code==200
        assert len(calls[1][1])==2
        assert 'verification_hint' not in calls[0][0]
        assert b.get(f'/api/items/{ident}/chat').json()['messages']==[]
        assert len(a.get(f'/api/items/{ident}/chat').json()['messages'])==4
        def fail(*args):raise ai.AIError('网络失败')
        monkeypatch.setattr(ai,'chat_reply',fail)
        assert a.post(f'/api/items/{ident}/chat',json={'message':'失败的问题'}).status_code==502
        assert len(a.get(f'/api/items/{ident}/chat').json()['messages'])==4


def test_cross_origin_and_search(app):
    with TestClient(app) as c:
        assert c.post('/api/auth/register',headers={'Origin':'https://other.invalid'},json={}).status_code==403
        account(c,'searcher');item(c)
        assert c.get('/api/items?q=蓝色').json()['total']==1
        assert c.get('/api/items?q=%25').json()['total']==0
        assert c.get('/api/items?category=钥匙').json()['total']==0


def test_demo_is_explicit_and_persistent(tmp_path):
    app=create_app(tmp_path,demo=True)
    with TestClient(app) as c:
        assert c.get('/api/items').json()['total']==8
        assert all(row['is_demo'] for row in c.get('/api/items').json()['items'])
        assert c.post('/api/auth/login',json={'username':'demo_lost','password':'demo123456'}).status_code==200
    with TestClient(app) as c:
        assert c.get('/api/items').json()['total']==8


def test_edit_close_delete_and_owner_permission(app):
    with TestClient(app) as owner,TestClient(app) as other:
        account(owner,'edit_owner');account(other,'edit_other');ident=item(owner,'lost')
        fields={'title':'更新后的蓝色杯子','category':'其他','description':'更新描述，蓝色杯子小猫贴纸','location':'图书馆一楼','occurred_on':date.today().isoformat(),'verification_hint':'updated-private'}
        assert other.patch(f'/api/items/{ident}',json=fields).status_code==403
        assert other.delete(f'/api/items/{ident}').status_code==403
        assert owner.patch(f'/api/items/{ident}',json=fields).status_code==200
        assert owner.get(f'/api/items/{ident}').json()['verification_hint']=='updated-private'
        assert owner.post(f'/api/items/{ident}/close').status_code==200
        assert owner.get('/api/items').json()['total']==0
        assert owner.get('/api/items?status=returned').json()['total']==1
        assert owner.patch(f'/api/items/{ident}',json=fields).status_code==409
        assert owner.delete(f'/api/items/{ident}').status_code==200
        assert owner.get(f'/api/items/{ident}').status_code==404


def test_ai_scores_reject_hallucinated_ids_and_nonfinite_values():
    candidates=[{'id':1}]
    raw={'matches':[{'id':1,'score':95},{'id':9999,'score':100},{'id':1,'score':float('nan')}]}
    result=validate_ai_matches(raw,candidates)
    assert len(result)==1 and result[0]['item']['id']==1
    with pytest.raises(ValueError):validate_ai_matches({'matches':[{'id':9999,'score':100}]},candidates)


def test_real_matches_do_not_use_demo_records(tmp_path,monkeypatch):
    app=create_app(tmp_path,demo=True)
    def fallback(*args):raise ai.AIError('测试规则模式')
    monkeypatch.setattr(ai,'rank_matches',fallback)
    with TestClient(app) as a,TestClient(app) as b:
        account(a,'real_lost');account(b,'real_found');target=item(a,'lost')
        assert a.post(f'/api/items/{target}/matches').json()['matches']==[]
        candidate=item(b)
        result=a.post(f'/api/items/{target}/matches').json()['matches']
        assert len(result)==1 and result[0]['item']['id']==candidate
        assert result[0]['item']['is_demo']==0


def test_profile_update_and_password_invalidates_other_sessions(app):
    with TestClient(app) as a, TestClient(app) as b:
        account(a,'profile_user')
        assert b.post('/api/auth/login',json={'username':'profile_user','password':'password123'}).status_code==200
        changed=a.patch('/api/auth/profile',json={'nickname':'新昵称','contact':'new-private-contact'})
        assert changed.status_code==200 and changed.json()['nickname']=='新昵称'
        assert a.get('/api/auth/me').json()['contact']=='new-private-contact'
        assert a.patch('/api/auth/profile',json={'nickname':'x','contact':' a '}).status_code==422
        assert a.post('/api/auth/password',json={'current_password':'bad','new_password':'updated123'}).status_code==400
        assert a.get('/api/auth/me').status_code==200
        assert a.post('/api/auth/password',json={'current_password':'password123','new_password':'updated123'}).status_code==200
        assert a.get('/api/auth/me').status_code==200
        assert b.get('/api/auth/me').status_code==401
        assert b.post('/api/auth/login',json={'username':'profile_user','password':'password123'}).status_code==401
        assert b.post('/api/auth/login',json={'username':'profile_user','password':'updated123'}).status_code==200


def test_withdraw_resubmit_and_review_revision(app):
    with TestClient(app) as owner,TestClient(app) as claimant,TestClient(app) as stranger:
        account(owner,'review_owner');account(claimant,'review_claimant');account(stranger,'review_other')
        ident=item(owner)
        body={'proof':'杯子底部刻有姓名，请核验'}
        claim=claimant.post(f'/api/items/{ident}/claims',json=body).json()['id']
        previous=owner.get('/api/me/claims').json()['claims'][0]['updated_at']
        assert stranger.post(f'/api/claims/{claim}/withdraw').status_code==403
        assert owner.post(f'/api/claims/{claim}/withdraw').status_code==403
        assert claimant.post(f'/api/claims/{claim}/withdraw').status_code==200
        assert claimant.get('/api/me/claims').json()['claims'][0]['note']=='申请者已撤回'
        assert claimant.post(f'/api/items/{ident}/claims',json=body).json()['id']==claim
        assert owner.post(f'/api/claims/{claim}/decision',json={'decision':'accept','expected_updated_at':previous}).status_code==409
        assert owner.post(f'/api/claims/{claim}/decision',json={'decision':'reject'}).status_code==200
        assert claimant.post(f'/api/items/{ident}/claims',json=body).status_code==409
        updated={'proof':'补充说明：杯底名字和内部贴纸可以核验'}
        assert claimant.post(f'/api/items/{ident}/claims',json=updated).status_code==200
        latest=owner.get('/api/me/claims').json()['claims'][0]['updated_at']
        assert owner.post(f'/api/claims/{claim}/decision',json={'decision':'accept','expected_updated_at':latest}).status_code==200
        assert claimant.post(f'/api/claims/{claim}/withdraw').status_code==409


def test_multipart_edit_photos_is_atomic(app):
    with TestClient(app) as owner,TestClient(app) as other:
        account(owner,'image_owner');account(other,'image_other')
        fields={'kind':'lost','title':'旧水杯信息','category':'其他','description':'旧水杯描述及特征','location':'图书馆二楼','occurred_on':date.today().isoformat()}
        photo=io.BytesIO();Image.new('RGB',(100,100),'red').save(photo,'PNG')
        ident=owner.post('/api/items',data=fields,files={'photo':('a.png',photo.getvalue(),'image/png')}).json()['id']
        old=owner.get(f'/api/items/{ident}').json()['photo_url']
        edit={**fields,'title':'新水杯信息'}
        assert other.put(f'/api/items/{ident}',data=edit).status_code==403
        assert owner.put(f'/api/items/{ident}',data=edit,files={'photo':('bad.png',b'not-an-image','image/png')}).status_code==422
        assert owner.get(f'/api/items/{ident}').json()['title']=='旧水杯信息'
        assert owner.get(old).status_code==200
        photo=io.BytesIO();Image.new('RGB',(100,100),'blue').save(photo,'PNG')
        assert owner.put(f'/api/items/{ident}',data=edit,files={'photo':('b.png',photo.getvalue(),'image/png')}).status_code==200
        new=owner.get(f'/api/items/{ident}').json()['photo_url']
        assert old!=new and owner.get(old).status_code==404 and owner.get(new).status_code==200
        assert owner.put(f'/api/items/{ident}',data={**edit,'clear_photo':'true'}).status_code==200
        assert owner.get(f'/api/items/{ident}').json()['photo_url'] is None
        assert owner.get(new).status_code==404


def test_date_filters_and_stripped_lengths(app):
    with TestClient(app) as c:
        account(c,'filter_user');item(c)
        today=date.today().isoformat()
        assert c.get(f'/api/items?date_from={today}&date_to={today}').json()['total']==1
        assert c.get('/api/items?date_from=2026-12-31&date_to=2026-01-01').status_code==422
        assert c.get('/api/items?date_from=bad').status_code==422
        data={'kind':'lost','title':' a ','category':'其他','description':'valid description','location':'location','occurred_on':today}
        assert c.post('/api/items',data=data).status_code==422


def test_matches_drop_stale_candidates_and_changed_target(app,monkeypatch):
    with TestClient(app) as a,TestClient(app) as b:
        account(a,'stale_lost');account(b,'stale_found');target=item(a,'lost');candidate=item(b)
        def close_candidate(target_data,candidates):
            with app.state.db.connect() as conn:conn.execute("UPDATE items SET status='returned' WHERE id=?",(candidate,))
            return {'matches':[{'id':candidate,'score':95}]}
        monkeypatch.setattr(ai,'rank_matches',close_candidate)
        assert a.post(f'/api/items/{target}/matches').json()['matches']==[]
        with app.state.db.connect() as conn:conn.execute("UPDATE items SET status='active' WHERE id=?",(candidate,))
        def change_target(target_data,candidates):
            with app.state.db.connect() as conn:conn.execute("UPDATE items SET updated_at='changed' WHERE id=?",(target,))
            return {'matches':[{'id':candidate,'score':95}]}
        monkeypatch.setattr(ai,'rank_matches',change_target)
        assert a.post(f'/api/items/{target}/matches').status_code==409


def test_reset_chat_does_not_delete_other_users_history(app,monkeypatch):
    calls=[]
    def chat(current,history,question):calls.append(history);return 'answer'
    monkeypatch.setattr(ai,'chat_reply',chat)
    with TestClient(app) as a,TestClient(app) as b:
        account(a,'reset_a');account(b,'reset_b');ident=item(a)
        a.post(f'/api/items/{ident}/chat',json={'message':'A question'})
        b.post(f'/api/items/{ident}/chat',json={'message':'B question'})
        assert a.delete(f'/api/items/{ident}/chat').status_code==200
        assert a.get(f'/api/items/{ident}/chat').json()['messages']==[]
        assert len(b.get(f'/api/items/{ident}/chat').json()['messages'])==2
        a.post(f'/api/items/{ident}/chat',json={'message':'new question'})
        assert calls[-1]==[]


def test_demo_accounts_keep_fixed_credentials(tmp_path):
    app=create_app(tmp_path,demo=True)
    with TestClient(app) as c:
        c.post('/api/auth/login',json={'username':'demo_lost','password':'demo123456'})
        assert c.patch('/api/auth/profile',json={'nickname':'new','contact':'new contact'}).status_code==403
        assert c.post('/api/auth/password',json={'current_password':'demo123456','new_password':'newpassword'}).status_code==403


def test_backup_is_consistent_and_does_not_include_env(app,tmp_path):
    import sqlite3,zipfile
    from campus_app.backup import backup
    with TestClient(app) as c:
        account(c,'backup_user')
        data={'kind':'found','title':'备份图片测试','category':'其他','description':'测试备份的照片内容','location':'图书馆','occurred_on':date.today().isoformat()}
        photo=io.BytesIO();Image.new('RGB',(80,80),'green').save(photo,'PNG')
        ident=c.post('/api/items',data=data,files={'photo':('image.png',photo.getvalue(),'image/png')}).json()['id']
        url=c.get(f'/api/items/{ident}').json()['photo_url']
        (app.state.db.directory/'.env').write_text('PRIVATE_KEY=not-for-backup')
        output=tmp_path/'snapshot.zip'
        backup(app.state.db.directory,output)
        with zipfile.ZipFile(output) as archive:
            assert set(archive.namelist())=={'campus.db',url.lstrip('/')}
            archive.extract('campus.db',tmp_path/'restored')
        with sqlite3.connect(tmp_path/'restored/campus.db') as conn:
            assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert conn.execute('SELECT COUNT(*) FROM items').fetchone()[0]==1
        assert output.stat().st_mode & 0o777==0o600
        with pytest.raises(ValueError):backup(app.state.db.directory,output)
