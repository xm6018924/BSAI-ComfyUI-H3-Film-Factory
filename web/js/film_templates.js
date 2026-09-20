/**
 * BSAI H3 Film Factory - 电影提示词模板库
 * v2.40 (2026-09-20)
 * 
 * 分类：
 * 1. 电影运镜 (Camera Movement)
 * 2. 电影调色 (Color Grading)
 * 3. 电影画面分割 (Aspect Ratio / Composition)
 * 4. 电影感 (Cinematic Feel)
 */

window.H3_FILM_TEMPLATES = {
  version: "1.0.0",
  categories: [
    {
      id: "camera",
      name: "电影运镜",
      name_en: "Camera Movement",
      icon: "🎥",
      templates: [
        {
          id: "cam_push_in",
          name: "缓推镜头",
          prompt: "【电影运镜·缓推】镜头缓慢向前推进，从全景逐渐聚焦到主体面部，营造紧张感与亲密感，焦点逐渐收紧，背景逐渐虚化。",
        },
        {
          id: "cam_pull_back",
          name: "拉远镜头",
          prompt: "【电影运镜·拉远】镜头缓慢向后拉远，从主体特写逐渐展现全景环境，营造孤独感与宏大叙事感，画面信息逐渐丰富。",
        },
        {
          id: "cam_pan_left",
          name: "左摇镜头",
          prompt: "【电影运镜·左摇】镜头从右向左水平摇动，流畅自然地扫过场景，引导观众视线跟随主体移动，营造探索感。",
        },
        {
          id: "cam_pan_right",
          name: "右摇镜头",
          prompt: "【电影运镜·右摇】镜头从左向右水平摇动，流畅自然地扫过场景，引导观众视线跟随主体移动，营造追踪感。",
        },
        {
          id: "cam_tilt_up",
          name: "上摇镜头",
          prompt: "【电影运镜·上摇】镜头从下向上垂直摇动，从脚部/地面逐渐摇到面部/天空，营造崇高感与仰视的压迫感。",
        },
        {
          id: "cam_tilt_down",
          name: "下摇镜头",
          prompt: "【电影运镜·下摇】镜头从上向下垂直摇动，从面部/天空逐渐摇到脚部/地面，营造审视感与宿命感。",
        },
        {
          id: "cam_tracking",
          name: "跟拍镜头",
          prompt: "【电影运镜·跟拍】镜头平稳跟随主体移动，保持主体在画面中心，轻微手持晃动增加真实感与沉浸感，如同旁观者视角。",
        },
        {
          id: "cam_dolly",
          name: "轨道推拉",
          prompt: "【电影运镜·轨道推拉】镜头沿轨道平滑移动，背景呈现视差滚动效果，画面稳定流畅，如同专业电影级运镜。",
        },
        {
          id: "cam_crane",
          name: "升降镜头",
          prompt: "【电影运镜·升降】镜头缓慢上升或下降，视角从平视逐渐变为俯视或仰视，营造史诗感与场面调度感。",
        },
        {
          id: "cam_orbit",
          name: "环绕镜头",
          prompt: "【电影运镜·环绕】镜头围绕主体做360度或半圆弧线运动，多角度展现主体与环境关系，营造沉浸式展示感。",
        },
        {
          id: "cam_handheld",
          name: "手持晃动",
          prompt: "【电影运镜·手持】镜头带有自然的手持晃动，节奏紧凑，营造纪实感与紧张感，如同现场实拍。",
        },
        {
          id: "cam_stedicam",
          name: "斯坦尼康",
          prompt: "【电影运镜·斯坦尼康】镜头平稳流畅，如同斯坦尼康拍摄，穿越复杂场景无卡顿，主体跟随自然，画面如丝般顺滑。",
        },
      ],
    },
    {
      id: "color",
      name: "电影调色",
      name_en: "Color Grading",
      icon: "🎨",
      templates: [
        {
          id: "color_warm",
          name: "暖色调",
          prompt: "【电影调色·暖调】整体画面偏暖，金色与橙色为主色调，肤色温暖红润，阴影带棕褐色调，营造温馨怀旧的氛围。",
        },
        {
          id: "color_cool",
          name: "冷色调",
          prompt: "【电影调色·冷调】整体画面偏冷，蓝色与青色为主色调，肤色偏苍白，阴影带深蓝灰色调，营造清冷孤寂的氛围。",
        },
        {
          id: "color_teal_orange",
          name: "青橙对比",
          prompt: "【电影调色·青橙对比】经典好莱坞调色风格，阴影偏青蓝色，高光偏橙黄色，对比强烈，视觉冲击力强，商业大片质感。",
        },
        {
          id: "color_film_noir",
          name: "黑白电影",
          prompt: "【电影调色·黑白电影】经典黑白电影质感，高对比度，深黑与纯白层次丰富，灰阶过渡自然，如同老胶片电影。",
        },
        {
          id: "color_pastel",
          name: "粉彩马卡龙",
          prompt: "【电影调色·粉彩】低饱和度马卡龙色调，柔和粉嫩，色彩淡雅清新，营造梦幻甜美氛围，日系清新风格。",
        },
        {
          id: "color_high_contrast",
          name: "高对比度",
          prompt: "【电影调色·高对比】高对比度调色，明暗反差强烈，暗部深邃，亮部通透，营造戏剧化与张力感。",
        },
        {
          id: "color_muted",
          name: "低饱和莫兰迪",
          prompt: "【电影调色·莫兰迪】低饱和度莫兰迪色调，灰调柔和，色彩克制内敛，营造高级感与文艺片氛围。",
        },
        {
          id: "color_neon",
          name: "霓虹赛博",
          prompt: "【电影调色·霓虹】赛博朋克风格，高饱和霓虹色，粉红与青蓝碰撞，夜间发光效果强烈，未来感十足。",
        },
        {
          id: "color_sepia",
          name: "复古棕褐",
          prompt: "【电影调色·棕褐】复古棕褐色调，如同老照片与老电影，泛黄怀旧，营造历史感与年代感。",
        },
        {
          id: "color_natural",
          name: "自然真实",
          prompt: "【电影调色·自然】自然真实色彩，还原物体本色，肤色自然通透，光影写实，如同纪录片质感。",
        },
      ],
    },
    {
      id: "composition",
      name: "画面分割",
      name_en: "Aspect / Composition",
      icon: "🎬",
      templates: [
        {
          id: "comp_widescreen",
          name: "宽屏电影感",
          prompt: "【画面分割·宽屏】2.39:1 宽屏电影比例，上下黑色遮幅，经典电影画幅，营造史诗感与影院体验。",
        },
        {
          id: "comp_letterbox",
          name: "上下黑边",
          prompt: "【画面分割·黑边】上下适度黑色遮幅，营造电影感，同时保留足够垂直空间展示主体。",
        },
        {
          id: "comp_rule_thirds",
          name: "三分构图",
          prompt: "【画面分割·三分】经典三分法构图，主体位于画面三分之一线交点，视觉平衡稳定，电影感十足。",
        },
        {
          id: "comp_center",
          name: "中心构图",
          prompt: "【画面分割·中心】主体居中对称构图，营造庄重感与仪式感，适合人物特写与正式场景。",
        },
        {
          id: "comp_leading",
          name: "引导线构图",
          prompt: "【画面分割·引导线】利用环境元素形成引导线，视线自然汇聚到主体，画面有深度感与纵深感。",
        },
        {
          id: "comp_frame_in_frame",
          name: "框中框",
          prompt: "【画面分割·框中框】利用门窗、镜子等元素形成框中框构图，增加画面层次与视觉趣味性。",
        },
      ],
    },
    {
      id: "cinematic",
      name: "电影感",
      name_en: "Cinematic Feel",
      icon: "✨",
      templates: [
        {
          id: "feel_cinematic",
          name: "电影级画质",
          prompt: "【电影感·画质】电影级画质，8K超高清，细节丰富，光影层次细腻，景深自然，胶片颗粒感适中。",
        },
        {
          id: "feel_dramatic_light",
          name: "戏剧化光影",
          prompt: "【电影感·光影】戏剧化布光，伦勃朗光效，明暗对比强烈，光影层次丰富，营造戏剧张力与氛围。",
        },
        {
          id: "feel_soft_light",
          name: "柔和柔光",
          prompt: "【电影感·柔光】柔和漫射光线，阴影边缘模糊，肤色细腻通透，营造温柔氛围与治愈感。",
        },
        {
          id: "feel_backlight",
          name: "逆光轮廓",
          prompt: "【电影感·逆光】逆光拍摄，主体边缘有金色轮廓光，背景过曝形成光晕，营造唯美感与梦幻感。",
        },
        {
          id: "feel_rainy",
          name: "雨夜氛围",
          prompt: "【电影感·雨夜】雨夜场景，地面反射灯光，雨滴清晰可见，雾气弥漫，营造忧郁浪漫的氛围。",
        },
        {
          id: "feel_sunset",
          name: "黄金时刻",
          prompt: "【电影感·黄金时刻】日落黄金时刻光线，暖金色侧光，长投影，天空渐变色彩，营造温暖怀旧氛围。",
        },
        {
          id: "feel_night_neon",
          name: "夜景霓虹",
          prompt: "【电影感·夜景】夜晚都市场景，霓虹灯光闪烁，灯光散景效果，湿滑路面反射，赛博朋克氛围。",
        },
        {
          id: "feel_misty",
          name: "雾气朦胧",
          prompt: "【电影感·雾气】雾气弥漫场景，远景朦胧模糊，空气透视明显，营造神秘氛围与诗意感。",
        },
        {
          id: "feel_tense",
          name: "紧张悬疑",
          prompt: "【电影感·紧张】低照度悬疑氛围，明暗对比强烈，阴影浓重，画面压抑，营造紧张与悬念感。",
        },
        {
          id: "feel_epic",
          name: "史诗宏大",
          prompt: "【电影感·史诗】史诗级宏大场面，广角镜头，开阔空间，人物渺小，营造历史感与命运感。",
        },
      ],
    },
  ],
};
