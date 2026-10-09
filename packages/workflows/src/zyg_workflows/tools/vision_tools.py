# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Vision tools using OpenCV, YOLOv8/ultralytics, Pillow, ImageHash, and diffusers.
"""

import json
import os

from zyg_workflows import paths
from zyg_workflows.bin import exe

try:
    from langchain.tools import BaseTool
except ImportError:
    try:
        from langchain_core.tools import BaseTool
    except ImportError:

        class BaseTool:
            name: str = ''
            description: str = ''

            def _run(self, *args, **kwargs):
                raise NotImplementedError


import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


class SceneChangeDetectorTool(BaseTool):
    name: str = 'Scene Change Detector (OpenCV)'
    description: str = (
        'Detect scene changes in a video using OpenCV frame differencing. Returns timestamps of detected scene cuts.'
    )

    def _run(
        self, video_path: str, threshold: float = 30.0, sample_every: int = 5, max_scan_seconds: float = 300.0
    ) -> str:
        import cv2
        import numpy as np
        import time

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        max_frames = int(fps * max_scan_seconds) if max_scan_seconds > 0 else 0
        prev_gray = None
        scene_times = []
        frame_idx = 0
        t_start = time.monotonic()
        truncated = False
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            # Hard frame cap: stop after max_scan_seconds worth of frames
            if max_frames > 0 and frame_idx >= max_frames:
                truncated = True
                break
            # Wall-clock safety: never spend more than max_scan_seconds + 30s total
            if max_scan_seconds > 0 and (time.monotonic() - t_start) > (max_scan_seconds + 30):
                truncated = True
                break
            if frame_idx % sample_every == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if prev_gray is not None:
                    diff = np.mean(np.abs(gray.astype(float) - prev_gray.astype(float)))
                    if diff > threshold:
                        scene_times.append(round(frame_idx / fps, 3))
                prev_gray = gray
            frame_idx += 1
        cap.release()
        return json.dumps(
            {
                'scene_count': len(scene_times),
                'scene_timestamps': scene_times,
                'total_frames': frame_idx,
                'fps': fps,
                'scan_seconds': round(frame_idx / fps, 1),
                'truncated': truncated,
            }
        )


class MotionScorerTool(BaseTool):
    name: str = 'Motion Scorer (ffmpeg parallel)'
    description: str = (
        'Scan an entire video and return a per-second motion intensity score. '
        'High scores indicate fights, reactions, sudden movements. '
        'Returns a list of {second, motion_score} entries sorted by score descending.'
    )

    def _run(self, video_path: str, sample_fps: float = 1.0, resize_width: int = 160, n_workers: int = 10) -> str:
        """
        Splits the video into n_workers equal chunks and processes all chunks
        in parallel via ffmpeg. Each chunk pipes raw grayscale frames into numpy
        for frame-diff motion scoring. ~12x faster than single-threaded.
        """
        import subprocess
        import numpy as np
        import concurrent.futures
        import threading

        # ── 1. Get duration and dimensions via ffprobe ──────────────────────
        probe = subprocess.run(
            [
                exe('ffprobe'),
                '-v',
                'error',
                '-select_streams',
                'v:0',
                '-show_entries',
                'stream=width,height',
                '-show_entries',
                'format=duration',
                '-of',
                'json',
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        try:
            info = json.loads(probe.stdout)
        except Exception:
            info = {}
        duration_s = float(info.get('format', {}).get('duration', 0) or 0)
        if duration_s <= 0:
            return json.dumps({'error': 'Could not determine video duration', 'all_scores': []})
        stream0 = (info.get('streams') or [{}])[0]
        orig_w = int(stream0.get('width') or 1920)
        orig_h = int(stream0.get('height') or 1080)
        scale_h = max(1, int(resize_width * orig_h / max(orig_w, 1)))
        frame_size = resize_width * scale_h

        # ── 2. Split into chunks and process in parallel ─────────────────────
        chunk_duration = duration_s / n_workers
        second_motion = {}  # second -> [diff_scores]
        lock = threading.Lock()

        def process_chunk(chunk_idx):
            start = chunk_idx * chunk_duration
            end = min(start + chunk_duration, duration_s)
            cmd = [
                'taskset',
                '-c',
                '0-19',
                'ffmpeg',
                '-hide_banner',
                '-threads',
                '2',
                '-ss',
                f'{start:.3f}',
                '-to',
                f'{end:.3f}',
                '-i',
                video_path,
                '-vf',
                f'scale={resize_width}:{scale_h},fps={sample_fps}',
                '-f',
                'rawvideo',
                '-pix_fmt',
                'gray',
                '-',
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            prev_frame = None
            frame_idx = 0
            local = {}
            while True:
                raw = proc.stdout.read(frame_size)
                if len(raw) < frame_size:
                    break
                frame = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
                if prev_frame is not None:
                    diff = float(np.mean(np.abs(frame - prev_frame)))
                    # Map local frame index back to absolute video second
                    sec = int(start + frame_idx / sample_fps)
                    local.setdefault(sec, []).append(diff)
                prev_frame = frame
                frame_idx += 1
            proc.stdout.close()
            proc.wait()
            with lock:
                for sec, vals in local.items():
                    second_motion.setdefault(sec, []).extend(vals)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            list(pool.map(process_chunk, range(n_workers)))

        # ── 3. Collapse per-second buckets → max score that second ──────────
        scored = [{'second': sec, 'motion_score': round(max(vals), 2)} for sec, vals in second_motion.items()]
        scored.sort(key=lambda x: x['motion_score'], reverse=True)

        return json.dumps(
            {
                'video_path': video_path,
                'duration_seconds': round(duration_s, 1),
                'sample_fps': sample_fps,
                'seconds_analyzed': len(scored),
                'top_motion_moments': scored[:50],
                'all_scores': sorted(scored, key=lambda x: x['second']),
            }
        )


class FaceDetectionTool(BaseTool):
    name: str = 'Face Detection (OpenCV / YOLOv8)'
    description: str = (
        'Detect faces in an image or video frame using OpenCV Haar cascade or YOLOv8. '
        'Returns bounding boxes and detection count.'
    )

    def _run(self, image_path: str, use_yolo: bool = False, confidence: float = 0.5) -> str:
        import cv2

        image = cv2.imread(image_path)
        if image is None:
            return json.dumps({'error': f'Cannot read image: {image_path}'})

        if use_yolo:
            try:
                from ultralytics import YOLO

                model = YOLO('yolov8n.pt')
                results = model(image, conf=confidence, classes=[0])  # class 0 = person
                boxes = []
                for r in results:
                    for box in r.boxes:
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        boxes.append({'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, 'conf': float(box.conf[0])})
                return json.dumps({'method': 'yolov8', 'detections': len(boxes), 'boxes': boxes})
            except Exception as e:
                _zyg_log.debug('yolov8 detection unavailable, falling back to the Haar cascade: %s', e)

        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        cascade = cv2.CascadeClassifier(cascade_path)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
        boxes = [{'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h)} for (x, y, w, h) in faces]
        return json.dumps({'method': 'opencv_haar', 'detections': len(boxes), 'boxes': boxes})


class YOLOv8SegmentTool(BaseTool):
    name: str = 'YOLOv8 Segment Anything (visual)'
    description: str = (
        'Run YOLOv8 instance segmentation on an image. '
        'Returns detected objects with class labels, confidence scores, and mask polygons.'
    )

    def _run(self, image_path: str, model_name: str = 'yolov8n-seg.pt', confidence: float = 0.5) -> str:
        from ultralytics import YOLO

        model = YOLO(model_name)
        results = model(image_path, conf=confidence)
        output = []
        for r in results:
            for i, box in enumerate(r.boxes):
                entry = {
                    'class': r.names[int(box.cls[0])],
                    'confidence': float(box.conf[0]),
                    'bbox': box.xyxy[0].tolist(),
                }
                if r.masks is not None and i < len(r.masks):
                    entry['mask_polygon'] = r.masks.xy[i].tolist()
                output.append(entry)
        return json.dumps({'detections': len(output), 'objects': output})


class TextOverlayRendererTool(BaseTool):
    name: str = 'Text Overlay Renderer (Pillow)'
    description: str = (
        'Render text overlay onto an image using Pillow. '
        'Supports custom font, size, color, position, and background box.'
    )

    def _run(
        self,
        image_path: str,
        text: str,
        output_path: str = '',
        x: int = 50,
        y: int = 50,
        font_size: int = 36,
        color: str = 'white',
        bg_color: str = '',
    ) -> str:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.open(image_path).convert('RGBA')
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', font_size)
        except Exception:
            font = ImageFont.load_default()

        if bg_color:
            bbox = draw.textbbox((x, y), text, font=font)
            draw.rectangle([bbox[0] - 4, bbox[1] - 4, bbox[2] + 4, bbox[3] + 4], fill=bg_color)
        draw.text((x, y), text, font=font, fill=color)

        if not output_path:
            base, ext = os.path.splitext(image_path)
            output_path = base + '_overlay' + (ext or '.png')

        img.convert('RGB').save(output_path)
        return json.dumps({'status': 'ok', 'output': output_path, 'text': text, 'position': [x, y]})


class VisualHashComparatorTool(BaseTool):
    name: str = 'Visual Hash Comparator (ImageHash + OpenCV)'
    description: str = (
        'Compute perceptual hash of images and compare similarity. '
        'Returns hash values and Hamming distance between two images.'
    )

    def _run(self, image_path_1: str, image_path_2: str = '', hash_type: str = 'phash') -> str:
        import imagehash
        from PIL import Image

        hash_fn = {
            'phash': imagehash.phash,
            'dhash': imagehash.dhash,
            'average_hash': imagehash.average_hash,
            'whash': imagehash.whash,
        }.get(hash_type, imagehash.phash)

        img1 = Image.open(image_path_1)
        h1 = hash_fn(img1)
        result = {'image1': image_path_1, 'hash1': str(h1), 'hash_type': hash_type}

        if image_path_2:
            img2 = Image.open(image_path_2)
            h2 = hash_fn(img2)
            distance = h1 - h2
            similarity = max(0.0, 1.0 - distance / 64.0)
            result.update(
                {
                    'image2': image_path_2,
                    'hash2': str(h2),
                    'hamming_distance': distance,
                    'similarity': round(similarity, 4),
                    'is_duplicate': distance < 10,
                }
            )
        return json.dumps(result)


class StableDiffusionTool(BaseTool):
    name: str = 'Stable Diffusion (background generation)'
    description: str = 'Generate images using a Stable Diffusion model via diffusers. Returns path to generated image.'

    def _run(
        self,
        prompt: str,
        output_path: str | None = None,
        model_id: str = 'stabilityai/stable-diffusion-2-1-base',
        steps: int = 20,
        width: int = 512,
        height: int = 512,
        guidance_scale: float = 7.5,
    ) -> str:
        import torch
        from diffusers import StableDiffusionPipeline

        if output_path is None:
            output_path = str(paths.tmp_dir('stable_diffusion') / 'sd_output.png')
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        dtype = torch.float16 if device == 'cuda' else torch.float32
        pipe = StableDiffusionPipeline.from_pretrained(model_id, torch_dtype=dtype)
        pipe = pipe.to(device)
        image = pipe(
            prompt, num_inference_steps=steps, width=width, height=height, guidance_scale=guidance_scale
        ).images[0]
        image.save(output_path)
        return json.dumps(
            {
                'status': 'ok',
                'output': output_path,
                'prompt': prompt,
                'model': model_id,
                'steps': steps,
                'size': f'{width}x{height}',
            }
        )


VISION_TOOLS = [
    SceneChangeDetectorTool(),
    FaceDetectionTool(),
    YOLOv8SegmentTool(),
    TextOverlayRendererTool(),
    VisualHashComparatorTool(),
    StableDiffusionTool(),
]

__all__ = [
    'SceneChangeDetectorTool',
    'FaceDetectionTool',
    'YOLOv8SegmentTool',
    'TextOverlayRendererTool',
    'VisualHashComparatorTool',
    'StableDiffusionTool',
    'VISION_TOOLS',
]
