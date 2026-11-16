"""
VHS 增强节点包
包含两个节点：
1. Video Combine+ (VHS_VideoCombineCustomPath) - 基于 Video Combine，增加自定义保存路径
2. Load Video (Custom+Latest) (VHS_LoadVideoCustomLatest) - 基于 LoadVideoPath，增加自定义文件夹自动选最新视频
"""

import os
import sys
import shutil

# ---------------------------------------------------------------------------
# 确保 VHS 插件路径在 sys.path 中，以便导入 videohelpersuite
# （移植版：本文件位于 Film-Factory/ported/，需上溯三层才到 custom_nodes）
# ---------------------------------------------------------------------------
_CUSTOM_NODES_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_VHS_DIR = os.path.join(_CUSTOM_NODES_DIR, "ComfyUI-VideoHelperSuite")
if os.path.isdir(_VHS_DIR) and _VHS_DIR not in sys.path:
    sys.path.insert(0, _VHS_DIR)

import folder_paths

from videohelpersuite.nodes import VideoCombine
from videohelpersuite.load_video_nodes import LoadVideoPath, video_extensions
from videohelpersuite.utils import hash_path, validate_path
from videohelpersuite.logger import logger


def resolve_save_dir(path_text):
    """把 custom_save_path 解析成绝对目录。

    - 绝对路径（含盘符 / 前导分隔符）：原样使用；
    - 相对路径：以 ComfyUI 的 output 目录为基准拼接，
      例如 "BSAI-MV\\分块2采" -> <ComfyUI>/output/BSAI-MV/分块2采。
    """
    text = path_text.strip().strip('"').strip("'")
    if os.path.isabs(text):
        return os.path.normpath(text)
    return os.path.normpath(os.path.join(folder_paths.get_output_directory(), text))


# ===========================================================================
# 节点1: Video Combine+ (自定义保存路径)
# ===========================================================================
class VideoCombineCustomPath(VideoCombine):
    """
    Video Combine 的增强版，新增 custom_save_path 参数。
    其余参数、行为与原 Video Combine 完全一致。
    """

    @classmethod
    def INPUT_TYPES(s):
        types = super().INPUT_TYPES()
        types["required"]["custom_save_path"] = (
            "STRING",
            {"default": "", "multiline": False},
        )
        return types

    RETURN_TYPES = ("VHS_FILENAMES",)
    RETURN_NAMES = ("Filenames",)
    OUTPUT_NODE = True
    CATEGORY = "Video Helper Suite 🎥🅥🅗🅢"
    FUNCTION = "combine_video"

    def combine_video(self, custom_save_path="", **kwargs):
        # 1. 调用父类方法，正常生成视频到 output 文件夹
        result = super().combine_video(**kwargs)

        if not isinstance(result, dict) or "result" not in result:
            return result

        save_output, output_files = result["result"][0]

        if not custom_save_path or not custom_save_path.strip():
            return result
        if not output_files:
            return result

        # 2. 找到带 "-audio" 后缀的视频文件（只复制带音频的）
        audio_file = None
        for f in output_files:
            if f and "-audio" in os.path.basename(f):
                audio_file = f
                break

        if audio_file is None:
            # 没有 -audio 变体说明这次合成没有音轨（audio 输入为空）。
            # 以前直接跳过 → 视频滞留在 output 根目录、自定义路径里什么都没有。
            # 现在退而求其次：仍把无音轨视频复制到自定义路径，只把情况打进日志。
            video_exts = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
            for f in output_files:
                if f and os.path.splitext(f)[1].lower() in video_exts and os.path.isfile(f):
                    audio_file = f
                    break
            if audio_file is None:
                logger.warn(
                    "[Video Combine+] 既没有带音频(-audio)的合成结果，也没有可用视频文件，"
                    "跳过自定义保存路径"
                )
                return result
            logger.warn(
                "[Video Combine+] 本次合成没有音轨（audio 输入为空），"
                f"将无音轨视频复制到自定义路径: {os.path.basename(audio_file)}"
            )

        if not os.path.isfile(audio_file):
            logger.error(f"[Video Combine+] 源音频视频文件不存在: {audio_file}")
            return result

        # 3. 确保目标文件夹存在（自动创建）；相对路径以 output 目录为基准
        target_dir = resolve_save_dir(custom_save_path)
        logger.info(f"[Video Combine+] 自定义保存目录解析: '{custom_save_path.strip()}' -> {target_dir}")
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"[Video Combine+] 创建目标文件夹失败: {target_dir}\n{e}")
            raise Exception(f"[Video Combine+] 创建目标文件夹失败: {target_dir}\n{e}")

        # 4. 自动重命名：同名文件加序号后缀
        base_name = os.path.basename(audio_file)
        name_part, ext_part = os.path.splitext(base_name)
        target_path = os.path.join(target_dir, base_name)
        rename_counter = 1
        while os.path.exists(target_path):
            target_path = os.path.join(
                target_dir, f"{name_part}_{rename_counter}{ext_part}"
            )
            rename_counter += 1

        # 5. 复制文件（copy2 保留时间戳等元数据）
        try:
            shutil.copy2(audio_file, target_path)
        except Exception as e:
            logger.error(
                f"[Video Combine+] 复制文件失败:\n  源: {audio_file}\n  目标: {target_path}\n{e}"
            )
            raise Exception(
                f"[Video Combine+] 复制文件失败:\n源: {audio_file}\n目标: {target_path}\n{e}"
            )

        # 6. 校验复制是否成功（文件存在 + 大小完全一致）
        if not os.path.isfile(target_path):
            raise Exception(f"[Video Combine+] 复制校验失败：目标文件不存在 {target_path}")

        src_size = os.path.getsize(audio_file)
        dst_size = os.path.getsize(target_path)
        if src_size != dst_size:
            try:
                os.remove(target_path)
            except Exception:
                pass
            raise Exception(
                f"[Video Combine+] 复制校验失败：文件大小不一致\n"
                f"  源文件: {src_size} 字节\n  目标文件: {dst_size} 字节"
            )

        logger.info(f"[Video Combine+] 视频已复制到自定义路径: {target_path}")

        # 7. 复制成功后，删除 output 文件夹中的全部生成文件
        deleted_count = 0
        for f in output_files:
            if f and os.path.isfile(f):
                try:
                    os.remove(f)
                    deleted_count += 1
                except Exception as e:
                    logger.warn(f"[Video Combine+] 删除 output 文件失败: {f}\n{e}")

        logger.info(f"[Video Combine+] 已清理 output 中的 {deleted_count} 个文件")

        # 8. 更新返回结果
        new_output_files = [target_path]
        result["result"] = ((save_output, new_output_files),)

        if result.get("ui", {}).get("gifs"):
            result["ui"]["gifs"][0]["fullpath"] = target_path
            result["ui"]["gifs"][0]["filename"] = os.path.basename(target_path)

        return result


# ===========================================================================
# 节点2: Load Video (Custom+Latest) (自定义文件夹 + 自动选最新)
# ===========================================================================
class LoadVideoCustomLatest(LoadVideoPath):
    """
    基于 LoadVideoPath 扩展，新增：
    - custom_folder: 自定义文件夹路径，填了就从该文件夹自动选视频
    - latest_index: 0=最新修改的视频，1=第二新的，2=第三新的...
    custom_folder 为空时，行为与原 LoadVideoPath 完全一致。
    """

    @classmethod
    def INPUT_TYPES(s):
        types = super().INPUT_TYPES()
        types["required"]["custom_folder"] = (
            "STRING",
            {"default": "", "multiline": False},
        )
        types["required"]["latest_index"] = (
            "INT",
            {"default": 0, "min": 0, "max": 999, "step": 1},
        )
        return types

    @staticmethod
    def _find_latest_video(folder, index):
        """从文件夹中按修改时间降序找到第 index 个视频文件（0=最新）"""
        if not os.path.isdir(folder):
            raise Exception(f"[Load Video+] 文件夹不存在: {folder}")
        videos = []
        for f in os.listdir(folder):
            full_path = os.path.join(folder, f)
            if os.path.isfile(full_path):
                ext = os.path.splitext(f)[1].lower().lstrip('.')
                if ext in video_extensions:
                    videos.append(full_path)
        if not videos:
            return None
        videos.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        if index >= len(videos):
            raise Exception(
                f"[Load Video+] latest_index={index} 超出范围，"
                f"文件夹中只有 {len(videos)} 个视频文件"
            )
        return videos[index]

    def load_video(self, custom_folder="", latest_index=0, **kwargs):
        if custom_folder and custom_folder.strip():
            video_path = self._find_latest_video(resolve_save_dir(custom_folder), latest_index)
            if video_path is None:
                raise Exception(
                    f"[Load Video+] 文件夹中没有找到视频文件: {custom_folder}"
                )
            kwargs['video'] = video_path
            logger.info(
                f"[Load Video+] 自动选择视频(第{latest_index}新): {video_path}"
            )
        return super().load_video(**kwargs)

    @classmethod
    def IS_CHANGED(s, video, custom_folder="", latest_index=0, **kwargs):
        if custom_folder and custom_folder.strip():
            try:
                video_path = s._find_latest_video(resolve_save_dir(custom_folder), latest_index)
                if video_path:
                    return hash_path(video_path)
            except Exception:
                pass
        return hash_path(video)

    @classmethod
    def VALIDATE_INPUTS(s, video, custom_folder="", latest_index=0, **kwargs):
        if custom_folder and custom_folder.strip():
            folder = resolve_save_dir(custom_folder)
            if not os.path.isdir(folder):
                return f"文件夹不存在: {folder}"
            has_video = any(
                os.path.splitext(f)[1].lower().lstrip('.') in video_extensions
                for f in os.listdir(folder)
                if os.path.isfile(os.path.join(folder, f))
            )
            if not has_video:
                return f"文件夹中没有视频文件: {folder}"
            return True
        return validate_path(video, allow_none=True)


# ---------------------------------------------------------------------------
# 节点注册
# ---------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "VHS_VideoCombineCustomPath": VideoCombineCustomPath,
    "VHS_LoadVideoCustomLatest": LoadVideoCustomLatest,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VHS_VideoCombineCustomPath": "Video Combine+ 🎥🅥🅗🅢",
    "VHS_LoadVideoCustomLatest": "Load Video (Custom+Latest) 🎥🅥🅗🅢",
}
