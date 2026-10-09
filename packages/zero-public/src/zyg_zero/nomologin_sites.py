# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Nomologin site catalogue — every posting destination the add-account form can offer.

Split out of nomologin.py because it is data, not logic: ~200 rows that change when a forum
dies or a policy flips, and nothing here should force a re-read of the launcher.

Each row is (key, label, home, compose, policy). `compose` is None when the site has no
distinct "post here" URL, in which case the home page is used. `policy` records whether an
outbound link to a YouTube channel actually survives on that site — the research behind it
is in NOMOLOGIN_SEEDING_SITES.md, and it is a *hint shown in the form*, never a gate:

    ok       outbound links are normal in posts
    earn     links allowed only after account age / karma / post history
    profile  links stripped from posts; bio or profile field only
    mirror   don't link — re-upload the video here
    hostile  auto-removed, or the destination is unreachable for that audience
             (mainland China cannot open a youtube.com link at all)

Policies were not measured — they are from research current to 2026-09 and each site's own
rules change without notice. Check before the first post.

Keys are stable: they name the target inside personas.json, so renaming one orphans that
target on every persona already carrying it. Add, don't rename.
"""

# Ordered. The form renders groups in this sequence and collapses all but the first.
CATALOGUE: dict[str, list[tuple]] = {
    # ── the original five plus the obvious neighbours ────────────────────────────────
    'Core': [
        ('x', 'X', 'https://x.com/home', 'https://x.com/compose/post', 'ok'),
        ('facebook', 'Facebook', 'https://www.facebook.com/', 'https://www.facebook.com/latest/posts', 'ok'),
        ('instagram', 'Instagram', 'https://www.instagram.com/', None, 'profile'),
        ('threads', 'Threads', 'https://www.threads.net/', None, 'ok'),
        ('youtube', 'YouTube', 'https://studio.youtube.com/', None, 'ok'),
        ('tiktok', 'TikTok', 'https://www.tiktok.com/', 'https://www.tiktok.com/tiktokstudio/upload', 'profile'),
        ('linkedin', 'LinkedIn', 'https://www.linkedin.com/feed/', None, 'ok'),
        ('reddit', 'Reddit', 'https://www.reddit.com/', 'https://www.reddit.com/submit', 'earn'),
        ('bluesky', 'Bluesky', 'https://bsky.app/', None, 'ok'),
        ('pinterest', 'Pinterest', 'https://www.pinterest.com/', 'https://www.pinterest.com/pin-builder/', 'ok'),
    ],
    # ── carries every language; start here ───────────────────────────────────────────
    'Universal — aggregators & publishing': [
        ('telegram', 'Telegram', 'https://web.telegram.org/', None, 'ok'),
        ('whatsapp', 'WhatsApp', 'https://web.whatsapp.com/', None, 'ok'),
        ('discord', 'Discord', 'https://discord.com/channels/@me', None, 'earn'),
        ('tumblr', 'Tumblr', 'https://www.tumblr.com/dashboard', None, 'ok'),
        ('medium', 'Medium', 'https://medium.com/', 'https://medium.com/new-story', 'ok'),
        ('substack', 'Substack', 'https://substack.com/', None, 'ok'),
        ('quora', 'Quora', 'https://www.quora.com/', None, 'earn'),
        ('mastodon', 'Mastodon', 'https://mastodon.social/', None, 'ok'),
        ('lemmy', 'Lemmy', 'https://lemmy.world/', None, 'ok'),
        ('flipboard', 'Flipboard', 'https://flipboard.com/', None, 'ok'),
        ('vocal_media', 'Vocal', 'https://vocal.media/', None, 'ok'),
        ('hackernews', 'Hacker News', 'https://news.ycombinator.com/submit', None, 'earn'),
    ],
    # ── mainland China: the GFW blocks youtube.com, so links are dead on arrival ─────
    'Chinese — Mainland (mirror, do not link)': [
        (
            'bilibili',
            'Bilibili',
            'https://www.bilibili.com/',
            'https://member.bilibili.com/platform/upload/video/frame',
            'mirror',
        ),
        ('douyin', 'Douyin', 'https://creator.douyin.com/', None, 'mirror'),
        ('kuaishou', 'Kuaishou', 'https://cp.kuaishou.com/', None, 'mirror'),
        ('xiaohongshu', 'Xiaohongshu', 'https://creator.xiaohongshu.com/', None, 'mirror'),
        ('weibo', 'Weibo', 'https://weibo.com/', None, 'hostile'),
        ('zhihu', 'Zhihu', 'https://www.zhihu.com/', None, 'hostile'),
        ('douban', 'Douban', 'https://www.douban.com/', None, 'hostile'),
        ('baidu_tieba', 'Baidu Tieba', 'https://tieba.baidu.com/', None, 'hostile'),
        ('toutiao', 'Toutiao', 'https://mp.toutiao.com/', None, 'mirror'),
        ('xigua', 'Xigua Video', 'https://studio.ixigua.com/', None, 'mirror'),
        ('youku', 'Youku', 'https://i.youku.com/', None, 'mirror'),
        ('tencent_video', 'Tencent Video', 'https://v.qq.com/', None, 'mirror'),
        ('iqiyi', 'iQiyi', 'https://www.iqiyi.com/', None, 'mirror'),
        ('weixin_oa', 'WeChat OA', 'https://mp.weixin.qq.com/', None, 'mirror'),
        ('coolapk', 'Coolapk', 'https://www.coolapk.com/', None, 'hostile'),
        ('jianshu', 'Jianshu', 'https://www.jianshu.com/', None, 'hostile'),
        ('sspai', 'Sspai', 'https://sspai.com/', None, 'hostile'),
        ('juejin', 'Juejin', 'https://juejin.cn/', None, 'hostile'),
        ('csdn', 'CSDN', 'https://www.csdn.net/', None, 'hostile'),
        ('nga', 'NGA', 'https://bbs.nga.cn/', None, 'hostile'),
        ('chiphell', 'Chiphell', 'https://www.chiphell.com/', None, 'hostile'),
        ('hupu', 'Hupu', 'https://bbs.hupu.com/', None, 'hostile'),
        ('v2ex', 'V2EX', 'https://www.v2ex.com/', None, 'earn'),
    ],
    # ── the Chinese-language audience that can actually open a YouTube link ──────────
    'Chinese — Taiwan': [
        ('ptt', 'PTT', 'https://www.ptt.cc/bbs/index.html', None, 'earn'),
        ('dcard', 'Dcard', 'https://www.dcard.tw/', None, 'earn'),
        ('mobile01', 'Mobile01', 'https://www.mobile01.com/', None, 'earn'),
        ('bahamut', 'Bahamut', 'https://forum.gamer.com.tw/', None, 'earn'),
        ('plurk', 'Plurk', 'https://www.plurk.com/', None, 'ok'),
        ('line_openchat', 'LINE OpenChat', 'https://openchat.line.me/', None, 'ok'),
        ('pixnet', 'Pixnet', 'https://www.pixnet.net/', None, 'ok'),
        ('komica', 'Komica', 'https://komica.org/', None, 'ok'),
        ('reddit_taiwan', 'r/taiwan', 'https://www.reddit.com/r/taiwan/submit', None, 'earn'),
    ],
    'Chinese — Hong Kong': [
        ('lihkg', 'LIHKG', 'https://lihkg.com/', None, 'earn'),
        ('discuss_hk', 'Discuss.com.hk', 'https://www.discuss.com.hk/', None, 'earn'),
        ('uwants', 'Uwants', 'https://www.uwants.com/', None, 'earn'),
        ('hkgolden', 'HKGolden', 'https://forum.hkgolden.com/', None, 'earn'),
        ('baby_kingdom', 'Baby-Kingdom', 'https://www.baby-kingdom.com/', None, 'earn'),
        ('openrice', 'OpenRice', 'https://www.openrice.com/', None, 'profile'),
        ('reddit_hongkong', 'r/HongKong', 'https://www.reddit.com/r/HongKong/submit', None, 'earn'),
    ],
    'Chinese — Singapore, Malaysia & diaspora': [
        ('hardwarezone', 'HardwareZone', 'https://forums.hardwarezone.com.sg/', None, 'earn'),
        ('lowyat', 'Lowyat.NET', 'https://forum.lowyat.net/', None, 'earn'),
        ('cari', 'Cari.com.my', 'https://www.cari.com.my/', None, 'earn'),
        ('wenxuecity', 'Wenxuecity', 'https://www.wenxuecity.com/', None, 'ok'),
        ('acres1p3', '1Point3Acres', 'https://www.1point3acres.com/bbs/', None, 'earn'),
        ('backchina', 'Backchina', 'https://www.backchina.com/', None, 'ok'),
    ],
    # ── YouTube is throttled in RU since Aug 2024; VK/Dzen downrank outbound YT ──────
    'Russian & CIS': [
        ('vk', 'VK', 'https://vk.com/feed', None, 'earn'),
        ('vk_video', 'VK Video', 'https://vkvideo.ru/', None, 'mirror'),
        ('ok_ru', 'Odnoklassniki', 'https://ok.ru/', None, 'ok'),
        ('dzen', 'Dzen', 'https://dzen.ru/', None, 'earn'),
        ('rutube', 'RuTube', 'https://rutube.ru/', None, 'mirror'),
        ('pikabu', 'Pikabu', 'https://pikabu.ru/', None, 'earn'),
        ('dtf', 'DTF', 'https://dtf.ru/', None, 'earn'),
        ('vc_ru', 'VC.ru', 'https://vc.ru/', None, 'earn'),
        ('habr', 'Habr', 'https://habr.com/ru/', None, 'earn'),
        ('yaplakal', 'YaPlakal', 'https://www.yaplakal.com/', None, 'earn'),
        ('fishki', 'Fishki.net', 'https://fishki.net/', None, 'earn'),
        ('joyreactor', 'JoyReactor', 'https://joyreactor.cc/', None, 'ok'),
        ('livejournal', 'LiveJournal', 'https://www.livejournal.com/', None, 'ok'),
        ('fourpda', '4PDA', 'https://4pda.to/', None, 'earn'),
        ('ixbt', 'iXBT', 'https://www.ixbt.com/', None, 'earn'),
        ('overclockers_ru', 'Overclockers.ru', 'https://overclockers.ru/', None, 'earn'),
        ('drive2', 'Drive2', 'https://www.drive2.ru/', None, 'earn'),
        ('drom', 'Drom', 'https://www.drom.ru/', None, 'earn'),
        ('stopgame', 'StopGame', 'https://stopgame.ru/', None, 'earn'),
        ('playground_ru', 'PlayGround.ru', 'https://www.playground.ru/', None, 'earn'),
        ('goha', 'GoHa', 'https://goha.ru/', None, 'earn'),
        ('author_today', 'Author.Today', 'https://author.today/', None, 'ok'),
        ('ficbook', 'Ficbook', 'https://ficbook.net/', None, 'ok'),
        ('otvet_mail', 'Otvet Mail.ru', 'https://otvet.mail.ru/', None, 'ok'),
        ('babyblog', 'BabyBlog', 'https://www.babyblog.ru/', None, 'earn'),
        ('baby_ru', 'Baby.ru', 'https://www.baby.ru/', None, 'earn'),
        ('umama', 'U-mama', 'https://www.u-mama.ru/', None, 'earn'),
        ('eva_ru', 'Eva.ru', 'https://eva.ru/', None, 'earn'),
        ('littleone', 'LittleOne', 'https://littleone.com/', None, 'earn'),
        ('woman_ru', 'Woman.ru', 'https://www.woman.ru/', None, 'earn'),
        ('spletnik', 'Spletnik', 'https://spletnik.ru/', None, 'earn'),
        ('rutracker', 'RuTracker', 'https://rutracker.org/forum/index.php', None, 'earn'),
        ('onliner_by', 'Onliner.by', 'https://www.onliner.by/', None, 'earn'),
        ('dou_ua', 'DOU.ua', 'https://dou.ua/', None, 'earn'),
    ],
    # ── no blocking, no throttling, no platform war: the best return on this list ────
    'Spanish — Spain': [
        ('meneame', 'Menéame', 'https://www.meneame.net/', 'https://www.meneame.net/submit', 'ok'),
        ('forocoches', 'Forocoches', 'https://forocoches.com/foro/', None, 'earn'),
        ('mediavida', 'Mediavida', 'https://www.mediavida.com/', None, 'earn'),
        ('elotrolado', 'ElOtroLado', 'https://www.elotrolado.net/', None, 'earn'),
        ('burbuja', 'Burbuja.info', 'https://www.burbuja.info/', None, 'ok'),
        ('tresdjuegos', '3DJuegos', 'https://www.3djuegos.com/comunidad/', None, 'earn'),
        ('vandal', 'Vandal', 'https://vandal.elespanol.com/foro/', None, 'earn'),
        ('xataka', 'Xataka', 'https://www.xataka.com/', None, 'earn'),
        ('hispasonic', 'HispaSonic', 'https://www.hispasonic.com/', None, 'earn'),
        ('domestika', 'Domestika', 'https://www.domestika.org/', None, 'earn'),
        ('bandaancha', 'Bandaancha', 'https://bandaancha.eu/', None, 'earn'),
        ('enfemenino', 'Enfemenino', 'https://www.enfemenino.com/', None, 'earn'),
        ('bebesymas', 'Bebés y más', 'https://www.bebesymas.com/', None, 'earn'),
        ('reddit_spain', 'r/spain', 'https://www.reddit.com/r/spain/submit', None, 'earn'),
        ('reddit_es', 'r/es', 'https://www.reddit.com/r/es/submit', None, 'earn'),
    ],
    'Spanish — Latin America': [
        ('taringa', 'Taringa!', 'https://www.taringa.net/', None, 'ok'),
        ('kwai', 'Kwai', 'https://www.kwai.com/', None, 'mirror'),
        ('quora_es', 'Quora en Español', 'https://es.quora.com/', None, 'earn'),
        ('reddit_mexico', 'r/mexico', 'https://www.reddit.com/r/mexico/submit', None, 'earn'),
        ('reddit_argentina', 'r/argentina', 'https://www.reddit.com/r/argentina/submit', None, 'earn'),
        ('reddit_chile', 'r/chile', 'https://www.reddit.com/r/chile/submit', None, 'earn'),
        ('reddit_colombia', 'r/colombia', 'https://www.reddit.com/r/colombia/submit', None, 'earn'),
        ('reddit_peru', 'r/PERU', 'https://www.reddit.com/r/PERU/submit', None, 'earn'),
        ('reddit_vzla', 'r/vzla', 'https://www.reddit.com/r/vzla/submit', None, 'earn'),
        ('reddit_uruguay', 'r/uruguay', 'https://www.reddit.com/r/uruguay/submit', None, 'earn'),
        ('reddit_latam', 'r/latinoamerica', 'https://www.reddit.com/r/latinoamerica/submit', None, 'earn'),
    ],
    'Portuguese — Brazil & Portugal': [
        ('hardmob', 'Hardmob', 'https://www.hardmob.com.br/', None, 'earn'),
        ('adrenaline', 'Adrenaline', 'https://forum.adrenaline.com.br/', None, 'earn'),
        ('clubedohardware', 'Clube do Hardware', 'https://www.clubedohardware.com.br/', None, 'earn'),
        ('tabnews', 'TabNews', 'https://www.tabnews.com.br/', None, 'earn'),
        ('zwame', 'ZWAME', 'https://zwame.pt/', None, 'earn'),
        ('reddit_brasil', 'r/brasil', 'https://www.reddit.com/r/brasil/submit', None, 'earn'),
        ('reddit_portugal', 'r/portugal', 'https://www.reddit.com/r/portugal/submit', None, 'earn'),
    ],
    'Japanese': [
        ('note_com', 'note', 'https://note.com/', None, 'ok'),
        ('hatena_bookmark', 'Hatena Bookmark', 'https://b.hatena.ne.jp/', None, 'ok'),
        ('hatena_blog', 'Hatena Blog', 'https://hatenablog.com/', None, 'ok'),
        ('fivech', '5ch', 'https://5ch.net/', None, 'ok'),
        ('nicovideo', 'Nicovideo', 'https://www.nicovideo.jp/', None, 'mirror'),
        ('pixiv', 'pixiv', 'https://www.pixiv.net/', None, 'profile'),
        ('togetter', 'Togetter', 'https://togetter.com/', None, 'ok'),
        ('qiita', 'Qiita', 'https://qiita.com/', None, 'earn'),
        ('zenn', 'Zenn', 'https://zenn.dev/', None, 'earn'),
        ('chiebukuro', 'Yahoo! Chiebukuro', 'https://chiebukuro.yahoo.co.jp/', None, 'earn'),
        ('ameba', 'Ameba Blog', 'https://www.ameba.jp/', None, 'ok'),
        ('reddit_japan', 'r/japan', 'https://www.reddit.com/r/japan/submit', None, 'earn'),
    ],
    'Korean': [
        ('naver_cafe', 'Naver Cafe', 'https://cafe.naver.com/', None, 'earn'),
        ('naver_blog', 'Naver Blog', 'https://blog.naver.com/', None, 'ok'),
        ('naver_kin', 'Naver Knowledge-iN', 'https://kin.naver.com/', None, 'earn'),
        ('naver_tv', 'Naver TV', 'https://tv.naver.com/', None, 'mirror'),
        ('dcinside', 'DCInside', 'https://www.dcinside.com/', None, 'ok'),
        ('fmkorea', 'FMKorea', 'https://www.fmkorea.com/', None, 'earn'),
        ('ruliweb', 'Ruliweb', 'https://bbs.ruliweb.com/', None, 'earn'),
        ('clien', 'Clien', 'https://www.clien.net/', None, 'earn'),
        ('ppomppu', 'PPOMPPU', 'https://www.ppomppu.co.kr/', None, 'earn'),
        ('mlbpark', 'MLBPark', 'https://mlbpark.donga.com/', None, 'earn'),
        ('theqoo', 'Theqoo', 'https://theqoo.net/', None, 'earn'),
        ('instiz', 'Instiz', 'https://www.instiz.net/', None, 'earn'),
        ('tistory', 'Tistory', 'https://www.tistory.com/', None, 'ok'),
        ('reddit_korea', 'r/korea', 'https://www.reddit.com/r/korea/submit', None, 'earn'),
    ],
    'German': [
        ('gutefrage', 'gutefrage.net', 'https://www.gutefrage.net/', None, 'earn'),
        ('mydealz', 'Mydealz', 'https://www.mydealz.de/', None, 'earn'),
        ('computerbase', 'ComputerBase', 'https://www.computerbase.de/forum/', None, 'earn'),
        ('hardwareluxx', 'Hardwareluxx', 'https://www.hardwareluxx.de/community/', None, 'earn'),
        ('gamestar', 'GameStar', 'https://www.gamestar.de/', None, 'earn'),
        ('motortalk', 'Motor-Talk', 'https://www.motor-talk.de/', None, 'earn'),
        ('urbia', 'Urbia', 'https://www.urbia.de/forum/', None, 'earn'),
        ('eltern_de', 'Eltern.de', 'https://www.eltern.de/foren/', None, 'earn'),
        ('werweisswas', 'wer-weiss-was', 'https://www.wer-weiss-was.de/', None, 'earn'),
        ('reddit_de', 'r/de', 'https://www.reddit.com/r/de/submit', None, 'earn'),
    ],
    'French': [
        ('jeuxvideo', 'JeuxVideo.com', 'https://www.jeuxvideo.com/forums/', None, 'ok'),
        ('doctissimo', 'Doctissimo', 'https://forum.doctissimo.fr/', None, 'earn'),
        ('magicmaman', 'Magicmaman', 'https://forum.magicmaman.com/', None, 'earn'),
        ('aufeminin', 'aufeminin', 'https://www.aufeminin.com/', None, 'earn'),
        ('hardwarefr', 'HardWare.fr', 'https://forum.hardware.fr/', None, 'earn'),
        ('dealabs', 'Dealabs', 'https://www.dealabs.com/', None, 'earn'),
        ('commentcamarche', 'CommentCaMarche', 'https://forums.commentcamarche.net/', None, 'earn'),
        ('dailymotion', 'Dailymotion', 'https://www.dailymotion.com/', None, 'mirror'),
        ('reddit_france', 'r/france', 'https://www.reddit.com/r/france/submit', None, 'earn'),
    ],
    'Polish': [
        ('wykop', 'Wykop.pl', 'https://wykop.pl/', None, 'ok'),
        ('kwejk', 'Kwejk', 'https://kwejk.pl/', None, 'ok'),
        ('filmweb', 'Filmweb', 'https://www.filmweb.pl/', None, 'earn'),
        ('elektroda', 'Elektroda', 'https://www.elektroda.pl/', None, 'earn'),
        ('ppe_pl', 'PPE.pl', 'https://www.ppe.pl/', None, 'earn'),
        ('reddit_polska', 'r/Polska', 'https://www.reddit.com/r/Polska/submit', None, 'earn'),
    ],
    'Turkish': [
        ('eksisozluk', 'Ekşi Sözlük', 'https://eksisozluk.com/', None, 'earn'),
        ('donanimhaber', 'DonanımHaber', 'https://forum.donanimhaber.com/', None, 'earn'),
        ('technopat', 'Technopat', 'https://www.technopat.net/sosyal/', None, 'earn'),
        ('incisozluk', 'İnci Sözlük', 'https://incisozluk.com.tr/', None, 'ok'),
        ('kizlarsoruyor', 'Kızlar Soruyor', 'https://www.kizlarsoruyor.com/', None, 'earn'),
        ('reddit_turkey', 'r/Turkey', 'https://www.reddit.com/r/Turkey/submit', None, 'earn'),
    ],
    'Southeast Asia': [
        ('kaskus', 'Kaskus', 'https://www.kaskus.co.id/', None, 'earn'),
        ('femaledaily', 'Female Daily', 'https://femaledaily.com/', None, 'earn'),
        ('voz', 'Voz.vn', 'https://voz.vn/', None, 'earn'),
        ('tinhte', 'Tinhte.vn', 'https://tinhte.vn/', None, 'earn'),
        ('webtretho', 'Webtretho', 'https://www.webtretho.com/', None, 'earn'),
        ('otofun', 'Otofun', 'https://www.otofun.net/', None, 'earn'),
        ('pantip', 'Pantip', 'https://pantip.com/', None, 'earn'),
        ('blockdit', 'Blockdit', 'https://www.blockdit.com/', None, 'ok'),
        ('dekd', 'Dek-D', 'https://www.dek-d.com/', None, 'earn'),
        ('pinoyexchange', 'PinoyExchange', 'https://www.pinoyexchange.com/', None, 'earn'),
        ('tipidpc', 'TipidPC', 'https://tipidpc.com/', None, 'earn'),
        ('reddit_indonesia', 'r/indonesia', 'https://www.reddit.com/r/indonesia/submit', None, 'earn'),
        ('reddit_thailand', 'r/Thailand', 'https://www.reddit.com/r/Thailand/submit', None, 'earn'),
        ('reddit_philippines', 'r/Philippines', 'https://www.reddit.com/r/Philippines/submit', None, 'earn'),
        ('reddit_vietnam', 'r/VietNam', 'https://www.reddit.com/r/VietNam/submit', None, 'earn'),
    ],
    'Indian languages': [
        ('sharechat', 'ShareChat', 'https://sharechat.com/', None, 'mirror'),
        ('moj', 'Moj', 'https://mojapp.in/', None, 'mirror'),
        ('quora_hi', 'Quora हिन्दी', 'https://hi.quora.com/', None, 'earn'),
        ('reddit_india', 'r/india', 'https://www.reddit.com/r/india/submit', None, 'earn'),
    ],
    'Arabic & Persian': [
        ('hsoub', 'Hsoub I/O', 'https://io.hsoub.com/', None, 'earn'),
        ('arabhardware', 'Arab Hardware', 'https://www.arabhardware.net/', None, 'earn'),
        ('aparat', 'Aparat', 'https://www.aparat.com/', None, 'mirror'),
        ('virgool', 'Virgool', 'https://virgool.io/', None, 'ok'),
        ('reddit_arabs', 'r/arabs', 'https://www.reddit.com/r/arabs/submit', None, 'earn'),
        ('reddit_egypt', 'r/Egypt', 'https://www.reddit.com/r/Egypt/submit', None, 'earn'),
    ],
    'Dutch & Belgian': [
        ('tweakers', 'Tweakers', 'https://tweakers.net/', None, 'earn'),
        ('fok', 'FOK!', 'https://forum.fok.nl/', None, 'ok'),
        ('dumpert', 'Dumpert', 'https://www.dumpert.nl/', None, 'ok'),
        ('viva_nl', 'Viva', 'https://forum.viva.nl/', None, 'earn'),
        ('ouders_nl', 'Ouders.nl', 'https://www.ouders.nl/', None, 'earn'),
        ('reddit_netherlands', 'r/thenetherlands', 'https://www.reddit.com/r/thenetherlands/submit', None, 'earn'),
        ('reddit_belgium', 'r/belgium', 'https://www.reddit.com/r/belgium/submit', None, 'earn'),
    ],
    'Italian': [
        ('tomshw_it', "Tom's Hardware IT", 'https://forum.tomshw.it/', None, 'earn'),
        ('hwupgrade', 'Hardware Upgrade', 'https://www.hwupgrade.it/forum/', None, 'earn'),
        ('everyeye', 'Everyeye', 'https://www.everyeye.it/', None, 'earn'),
        ('alfemminile', 'alfemminile', 'https://www.alfemminile.com/', None, 'earn'),
        ('reddit_italy', 'r/italy', 'https://www.reddit.com/r/italy/submit', None, 'earn'),
    ],
    'Nordic': [
        ('flashback', 'Flashback', 'https://www.flashback.org/', None, 'ok'),
        ('sweclockers', 'SweClockers', 'https://www.sweclockers.com/forum', None, 'earn'),
        ('suomi24', 'Suomi24', 'https://keskustelu.suomi24.fi/', None, 'ok'),
        ('vauva', 'Vauva.fi', 'https://www.vauva.fi/keskustelu', None, 'ok'),
        ('reddit_sweden', 'r/sweden', 'https://www.reddit.com/r/sweden/submit', None, 'earn'),
        ('reddit_suomi', 'r/Suomi', 'https://www.reddit.com/r/Suomi/submit', None, 'earn'),
    ],
    'Central & Eastern Europe': [
        ('modrykonik', 'Modrý koník', 'https://www.modrykonik.sk/', None, 'earn'),
        ('zive_cz', 'Živě.cz', 'https://www.zive.cz/', None, 'earn'),
        ('diit_cz', 'Diit.cz', 'https://diit.cz/', None, 'earn'),
        ('hardverapro', 'HardverApró', 'https://hardverapro.hu/', None, 'earn'),
        ('gyakorikerdesek', 'Gyakorikérdések', 'https://www.gyakorikerdesek.hu/', None, 'earn'),
        ('softpedia_forum', 'Softpedia Forum', 'https://forum.softpedia.com/', None, 'earn'),
        ('insomnia_gr', 'Insomnia.gr', 'https://www.insomnia.gr/', None, 'earn'),
        ('fxp', 'FXP', 'https://www.fxp.co.il/', None, 'earn'),
        ('reddit_czech', 'r/czech', 'https://www.reddit.com/r/czech/submit', None, 'earn'),
        ('reddit_hungary', 'r/hungary', 'https://www.reddit.com/r/hungary/submit', None, 'earn'),
        ('reddit_romania', 'r/Romania', 'https://www.reddit.com/r/Romania/submit', None, 'earn'),
        ('reddit_greece', 'r/greece', 'https://www.reddit.com/r/greece/submit', None, 'earn'),
        ('reddit_israel', 'r/Israel', 'https://www.reddit.com/r/Israel/submit', None, 'earn'),
        ('reddit_ukraine', 'r/Ukraine', 'https://www.reddit.com/r/Ukraine/submit', None, 'earn'),
    ],
    'Video mirrors': [
        ('odysee', 'Odysee', 'https://odysee.com/', None, 'mirror'),
        ('rumble', 'Rumble', 'https://rumble.com/', None, 'mirror'),
        ('vimeo', 'Vimeo', 'https://vimeo.com/', None, 'mirror'),
        ('peertube', 'PeerTube', 'https://joinpeertube.org/', None, 'mirror'),
    ],
}

GROUPS: list[str] = list(CATALOGUE)

POLICY_NOTE = {
    'ok': 'links are normal here',
    'earn': 'needs account history before you link',
    'profile': 'links only in the profile, stripped from posts',
    'mirror': 're-upload the video — do not link',
    'hostile': 'links are removed, or unreachable for this audience',
}


def _build() -> dict[str, dict]:
    sites, seen = {}, {}
    for group, rows in CATALOGUE.items():
        for key, label, home, compose, policy in rows:
            if key in seen:
                raise ValueError(
                    f'duplicate platform key {key!r} in {group!r} '
                    f'and {seen[key]!r} — a key names a target in '
                    f'personas.json and cannot be shared'
                )
            seen[key] = group
            sites[key] = {'label': label, 'home': home, 'compose': compose or home, 'group': group, 'policy': policy}
    return sites


SITES: dict[str, dict] = _build()


if __name__ == '__main__':
    import collections

    by_policy = collections.Counter(s['policy'] for s in SITES.values())
    print(f'{len(SITES)} sites in {len(GROUPS)} groups')
    for g in GROUPS:
        print(f'  {len(CATALOGUE[g]):>3}  {g}')
    print('policy:', dict(by_policy))
