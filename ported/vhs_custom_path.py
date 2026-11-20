"""
VHS enhanced node pack (ported into BSAI Film Factory).
Two nodes:
1. Video Combine+ (VHS_VideoCombineCustomPath) - Video Combine plus a custom save path
2. Load Video (Custom+Latest) (VHS_LoadVideoCustomLatest) - LoadVideoPath plus auto-latest from a folder

Security contract (see ComfyUI-Manager PR #3497 review):
- every user-supplied path is checked as TEXT before any isdir/listdir/makedirs/
  copy/isfile call;
- network shares (UNC, `\\\\host\\share` or `//host/share`) are rejected;
- `..` segments are rejected;
- custom_save_path must resolve (realpath) inside ComfyUI's output directory.
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


def _is_network_share_text(text):
    """True when the raw widget text points at a network share (UNC).

    Checked on the STRING only, so it runs before any filesystem call and
    never touches a share (which would leak the Windows session credentials).
    """
    if not text:
        return False
    value = str(text).strip().strip('"').strip("'")
    if not value:
        return False
    # A Windows UNC path may also arrive with forward slashes.
    return value.replace("\\", "/").startswith("//")


def _has_parent_segment(text):
    value = str(text or "").strip().strip('"').strip("'")
    return any(part == ".." for part in value.replace("\\", "/").split("/"))


def _reject_reason(path_text, what="path"):
    """Return an error string when the raw text is unsafe, else None."""
    if _is_network_share_text(path_text):
        return "%s refused: network shares are not allowed (%s)" % (what, path_text)
    if _has_parent_segment(path_text):
        return "%s refused: '..' segments are not allowed (%s)" % (what, path_text)
    return None


def _output_root():
    return os.path.realpath(folder_paths.get_output_directory())


def resolve_save_dir(path_text):
    """Resolve custom_save_path to an absolute directory inside output/.

    - empty text -> ValueError (the caller decides whether that is fatal);
    - network share text -> ValueError before touching the filesystem;
    - `..` segments -> ValueError;
    - relative text is joined onto the output directory;
    - the final realpath must stay under output/, otherwise ValueError.
    """
    text = str(path_text or "").strip().strip('"').strip("'")
    if not text:
        raise ValueError("custom save path is empty")
    reason = _reject_reason(text, "custom save path")
    if reason:
        raise ValueError(reason)
    candidate = text if os.path.isabs(text) else os.path.join(
        folder_paths.get_output_directory(), text)
    full = os.path.realpath(os.path.normpath(candidate))
    root = _output_root()
    try:
        inside = os.path.commonpath([root, full]) == root
    except ValueError:
        inside = False
    if not inside:
        raise ValueError(
            "custom save path refused: path must stay inside the output directory (%s)" % text)
    return full


def resolve_read_dir(path_text):
    """Resolve a read-only folder widget (custom_folder).

    Network shares and `..` are rejected as text; plain local absolute paths
    stay allowed so existing graphs that read from another local disk keep
    working.
    """
    text = str(path_text or "").strip().strip('"').strip("'")
    if not text:
        raise ValueError("folder path is empty")
    reason = _reject_reason(text, "folder path")
    if reason:
        raise ValueError(reason)
    candidate = text if os.path.isabs(text) else os.path.join(
        folder_paths.get_output_directory(), text)
    return os.path.realpath(os.path.normpath(candidate))


# ===========================================================================
# 节点1: Video Combine+ (自定义保存路径)
# ===========================================================================
class VideoCombineCustomPath(VideoCombine):
    """
    Video Combine with an extra custom_save_path parameter.
    Every other parameter and behaviour matches the original node.
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

    @classmethod
    def VALIDATE_INPUTS(s, custom_save_path="", **kwargs):
        # Text-only pre-check: no join, no realpath, no makedirs on a share.
        if custom_save_path and str(custom_save_path).strip():
            try:
                resolve_save_dir(custom_save_path)
            except ValueError as exc:
                return str(exc)
        return True

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
            # No -audio variant means this render had no soundtrack (audio input empty).
            # Fall back to the silent video instead of leaving it in output/.
            video_exts = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
            for f in output_files:
                if f and os.path.splitext(f)[1].lower() in video_exts and os.path.isfile(f):
                    audio_file = f
                    break
            if audio_file is None:
                logger.warn(
                    "[Video Combine+] no -audio render and no usable video file; "
                    "skipping the custom save path"
                )
                return result
            logger.warn(
                "[Video Combine+] this render has no soundtrack (audio input empty); "
                "copying the silent video to the custom path: %s"
                % os.path.basename(audio_file)
            )

        if not os.path.isfile(audio_file):
            logger.error("[Video Combine+] source video file is missing: %s" % audio_file)
            return result

        # 3. Resolve and create the target folder (must stay inside output/)
        try:
            target_dir = resolve_save_dir(custom_save_path)
        except ValueError as exc:
            logger.error("[Video Combine+] custom save path rejected: %s" % exc)
            raise Exception("[Video Combine+] custom save path rejected: %s" % exc)
        logger.info(
            "[Video Combine+] custom save dir: '%s' -> %s"
            % (custom_save_path.strip(), target_dir)
        )
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as e:
            logger.error(
                "[Video Combine+] failed to create the target folder: %s\n%s" % (target_dir, e))
            raise Exception(
                "[Video Combine+] failed to create the target folder: %s\n%s" % (target_dir, e))

        # 4. Auto-rename: append a counter when the name is taken
        base_name = os.path.basename(audio_file)
        name_part, ext_part = os.path.splitext(base_name)
        target_path = os.path.join(target_dir, base_name)
        rename_counter = 1
        while os.path.exists(target_path):
            target_path = os.path.join(
                target_dir, "%s_%d%s" % (name_part, rename_counter, ext_part)
            )
            rename_counter += 1

        # 5. Copy the file (copy2 keeps timestamps and metadata)
        try:
            shutil.copy2(audio_file, target_path)
        except Exception as e:
            logger.error(
                "[Video Combine+] copy failed:\n  source: %s\n  target: %s\n%s"
                % (audio_file, target_path, e)
            )
            raise Exception(
                "[Video Combine+] copy failed:\nsource: %s\ntarget: %s\n%s"
                % (audio_file, target_path, e)
            )

        # 6. Verify the copy (file exists and size matches)
        if not os.path.isfile(target_path):
            raise Exception(
                "[Video Combine+] copy verification failed: target is missing %s" % target_path)

        src_size = os.path.getsize(audio_file)
        dst_size = os.path.getsize(target_path)
        if src_size != dst_size:
            try:
                os.remove(target_path)
            except Exception:
                pass
            raise Exception(
                "[Video Combine+] copy verification failed: size mismatch\n"
                "  source: %d bytes\n  target: %d bytes" % (src_size, dst_size)
            )

        logger.info("[Video Combine+] video copied to the custom path: %s" % target_path)

        # 7. Remove the generated files from output/ after a successful copy
        deleted_count = 0
        for f in output_files:
            if f and os.path.isfile(f):
                try:
                    os.remove(f)
                    deleted_count += 1
                except Exception as e:
                    logger.warn(
                        "[Video Combine+] failed to delete an output file: %s\n%s" % (f, e))

        logger.info("[Video Combine+] cleaned %d file(s) from output/" % deleted_count)

        # 8. Update the returned result
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
    LoadVideoPath with:
    - custom_folder: a folder to pick the video from automatically
    - latest_index: 0 = newest, 1 = second newest, ...
    Empty custom_folder keeps the original LoadVideoPath behaviour.
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
        """Pick the index-th newest video (0 = newest) from an already vetted folder."""
        if not os.path.isdir(folder):
            raise Exception("[Load Video+] folder does not exist: %s" % folder)
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
                "[Load Video+] latest_index=%d is out of range; "
                "the folder holds %d video file(s)" % (index, len(videos))
            )
        return videos[index]

    def load_video(self, custom_folder="", latest_index=0, **kwargs):
        if custom_folder and custom_folder.strip():
            try:
                folder = resolve_read_dir(custom_folder)
            except ValueError as exc:
                raise Exception("[Load Video+] %s" % exc)
            video_path = self._find_latest_video(folder, latest_index)
            if video_path is None:
                raise Exception(
                    "[Load Video+] no video file found in folder: %s" % custom_folder
                )
            kwargs['video'] = video_path
            logger.info(
                "[Load Video+] auto-selected video (newest #%d): %s"
                % (latest_index, video_path)
            )
        return super().load_video(**kwargs)

    @classmethod
    def IS_CHANGED(s, video, custom_folder="", latest_index=0, **kwargs):
        if custom_folder and custom_folder.strip():
            try:
                video_path = s._find_latest_video(resolve_read_dir(custom_folder), latest_index)
                if video_path:
                    return hash_path(video_path)
            except Exception:
                pass
        return hash_path(video)

    @classmethod
    def VALIDATE_INPUTS(s, video, custom_folder="", latest_index=0, **kwargs):
        if custom_folder and custom_folder.strip():
            try:
                folder = resolve_read_dir(custom_folder)
            except ValueError as exc:
                return str(exc)
            if not os.path.isdir(folder):
                return "folder does not exist: %s" % folder
            try:
                has_video = any(
                    os.path.splitext(f)[1].lower().lstrip('.') in video_extensions
                    for f in os.listdir(folder)
                    if os.path.isfile(os.path.join(folder, f))
                )
            except OSError as exc:
                return "folder cannot be read: %s (%s)" % (folder, exc)
            if not has_video:
                return "folder holds no video file: %s" % folder
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
