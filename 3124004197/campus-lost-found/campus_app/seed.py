from datetime import date, datetime, timedelta, timezone
from .security import hash_password


def seed_demo(db):
    with db.connect() as conn:
        if conn.execute('SELECT 1 FROM items WHERE is_demo=1').fetchone():return
        stamp=datetime.now(timezone.utc).isoformat()
        for username,nickname in [('demo_lost','演示同学 A'),('demo_found','演示同学 B')]:
            conn.execute('INSERT OR IGNORE INTO users(username,nickname,password_hash,contact,created_at) VALUES(?,?,?,?,?)',
                         (username,nickname,hash_password('demo123456'),'演示联系方式，不用于真实联系',stamp))
        owners={row['username']:row['id'] for row in conn.execute("SELECT id,username FROM users WHERE username IN ('demo_lost','demo_found')")}
        entries=[
            ('lost','蓝色保温杯','其他','深蓝色杯身，白色杯盖，杯身有一张小猫贴纸。','图书馆二楼','demo_lost'),
            ('found','图书馆拾得蓝色水杯','其他','蓝色保温杯，白色盖子，有小猫贴纸，已交到图书馆服务台。','图书馆二楼服务台','demo_found'),
            ('found','一串钥匙','钥匙','两把钥匙，挂着一个绿色编织挂绳。','教学楼门口','demo_found'),
            ('lost','绿色挂绳钥匙','钥匙','一串两把钥匙，带绿色挂绳，可能落在上课路上。','教学楼附近','demo_lost'),
            ('found','黑色无线耳机盒','数码设备','黑色耳机充电盒，没有明显品牌标识。','操场看台','demo_found'),
            ('lost','灰色帆布笔袋','文具书籍','灰色拉链笔袋，装有几支中性笔和一把尺子。','自习室','demo_lost'),
            ('found','米白色围巾','衣物配饰','米白色针织围巾，已暂存于食堂值班处。','食堂一楼','demo_found'),
            ('lost','校园卡','证件卡片','卡套为透明磨砂材质，卡片上有姓名，未公开学号。','宿舍至图书馆路上','demo_lost')]
        for i,(kind,title,category,description,location,owner) in enumerate(entries):
            conn.execute('INSERT INTO items(owner_id,kind,title,category,description,location,occurred_on,verification_hint,is_demo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,1,?,?)',
                         (owners[owner],kind,title,category,description,location,(date.today()-timedelta(days=i//3)).isoformat(),'演示私密核验特征，请使用真实物品时自行设置',stamp,stamp))
