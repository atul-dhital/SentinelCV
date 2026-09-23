"""
Advanced Data Augmentation Module for Face Recognition
Implements CutMix, MixUp, Random Erasing, and other advanced techniques
"""

import cv2
import numpy as np
from typing import Tuple, Optional, List
import random


class AdvancedAugmentation:
    """Advanced augmentation techniques for face recognition training"""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.rotation_angle_range = self.config.get('rotation_angle_range', (-15, 15))
        self.scale_factor_range = self.config.get('scale_factor_range', (0.9, 1.1))
        self.flip_probability = self.config.get('flip_probability', 0.5)
        self.jitter_intensity = self.config.get('jitter_intensity', 0.2)
        self.cutout_percentage = self.config.get('cutout_percentage', 0.3)
        self.mixup_alpha = self.config.get('mixup_alpha', 0.2)
        self.cutmix_alpha = self.config.get('cutmix_alpha', 1.0)
        
    def rotate_image(self, image: np.ndarray, angle: float) -> np.ndarray:
        """Rotate image by given angle around center"""
        h, w = image.shape[:2]
        center = (w // 2, h // 2)
        
        rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        
        cos_val = np.abs(rotation_matrix[0, 0])
        sin_val = np.abs(rotation_matrix[0, 1])
        
        new_w = int((h * sin_val) + (w * cos_val))
        new_h = int((h * cos_val) + (w * sin_val))
        
        rotation_matrix[0, 2] += (new_w / 2) - center[0]
        rotation_matrix[1, 2] += (new_h / 2) - center[1]
        
        rotated = cv2.warpAffine(image, rotation_matrix, (new_w, new_h), 
                                  borderMode=cv2.BORDER_REFLECT)
        return rotated
    
    def random_rotation(self, image: np.ndarray) -> np.ndarray:
        """Apply random rotation within configured range"""
        angle = random.uniform(self.rotation_angle_range[0], self.rotation_angle_range[1])
        return self.rotate_image(image, angle)
    
    def random_scale(self, image: np.ndarray) -> np.ndarray:
        """Apply random scaling"""
        scale = random.uniform(self.scale_factor_range[0], self.scale_factor_range[1])
        h, w = image.shape[:2]
        new_w = int(w * scale)
        new_h = int(h * scale)
        scaled = cv2.resize(image, (new_w, new_h))
        
        if scale > 1.0:
            start_x = (new_w - w) // 2
            start_y = (new_h - h) // 2
            return scaled[start_y:start_y+h, start_x:start_x+w]
        else:
            padded = np.zeros((h, w, 3), dtype=image.dtype)
            start_x = (w - new_w) // 2
            start_y = (h - new_h) // 2
            padded[start_y:start_y+new_h, start_x:start_x+new_w] = scaled
            return padded
    
    def random_flip(self, image: np.ndarray) -> np.ndarray:
        """Apply random horizontal flip"""
        if random.random() < self.flip_probability:
            return cv2.flip(image, 1)
        return image
    
    def color_jitter(self, image: np.ndarray) -> np.ndarray:
        """Apply color jittering (brightness, contrast, saturation)"""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
        
        brightness_factor = 1.0 + random.uniform(-self.jitter_intensity, self.jitter_intensity)
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * brightness_factor, 0, 255)
        
        contrast_factor = 1.0 + random.uniform(-self.jitter_intensity, self.jitter_intensity)
        hsv[:, :, 2] = np.clip((hsv[:, :, 2] - 128) * contrast_factor + 128, 0, 255)
        
        saturation_factor = 1.0 + random.uniform(-self.jitter_intensity, self.jitter_intensity)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation_factor, 0, 255)
        
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    def random_erasing(self, image: np.ndarray) -> np.ndarray:
        """Apply random erasing (CutOut)"""
        h, w = image.shape[:2]
        area = h * w
        
        target_area = random.uniform(0.02, self.cutout_percentage) * area
        aspect_ratio = random.uniform(0.3, 3.0)
        
        erase_h = int(np.sqrt(target_area * aspect_ratio))
        erase_w = int(np.sqrt(target_area / aspect_ratio))
        
        if erase_w < w and erase_h < h:
            x = random.randint(0, w - erase_w)
            y = random.randint(0, h - erase_h)
            
            image[y:y+erase_h, x:x+erase_w] = np.random.randint(0, 256, (erase_h, erase_w, 3), dtype=np.uint8)
        
        return image
    
    def cutmix(self, image1: np.ndarray, image2: np.ndarray) -> np.ndarray:
        """Apply CutMix augmentation"""
        h, w = image1.shape[:2]
        
        lam = np.random.beta(self.cutmix_alpha, self.cutmix_alpha)
        
        cut_ratio = np.sqrt(1.0 - lam)
        cut_h = int(h * cut_ratio)
        cut_w = int(w * cut_ratio)
        
        cx = np.random.randint(w)
        cy = np.random.randint(h)
        
        x1 = np.clip(cx - cut_w // 2, 0, w)
        y1 = np.clip(cy - cut_h // 2, 0, h)
        x2 = np.clip(cx + cut_w // 2, 0, w)
        y2 = np.clip(cy + cut_h // 2, 0, h)
        
        result = image1.copy()
        result[y1:y2, x1:x2] = image2[y1:y2, x1:x2]
        
        return result
    
    def mixup(self, image1: np.ndarray, image2: np.ndarray) -> Tuple[np.ndarray, float]:
        """Apply MixUp augmentation"""
        lam = np.random.beta(self.mixup_alpha, self.mixup_alpha)
        
        result = (lam * image1.astype(np.float32) + (1 - lam) * image2.astype(np.float32)).astype(np.uint8)
        
        return result, lam
    
    def apply_augmentation_pipeline(self, image: np.ndarray, augmentations: List[str] = None) -> np.ndarray:
        """Apply a pipeline of augmentations"""
        if augmentations is None:
            augmentations = ['rotate', 'flip', 'jitter', 'erase']
        
        result = image.copy()
        
        for aug in augmentations:
            if aug == 'rotate' and random.random() < 0.7:
                result = self.random_rotation(result)
            elif aug == 'scale' and random.random() < 0.7:
                result = self.random_scale(result)
            elif aug == 'flip' and random.random() < 0.7:
                result = self.random_flip(result)
            elif aug == 'jitter' and random.random() < 0.7:
                result = self.color_jitter(result)
            elif aug == 'erase' and random.random() < 0.5:
                result = self.random_erasing(result)
        
        return result
    
    def augment_batch(self, images: List[np.ndarray], method: str = 'pipeline') -> List[np.ndarray]:
        """Augment a batch of images"""
        if method == 'pipeline':
            return [self.apply_augmentation_pipeline(img) for img in images]
        elif method == 'mixed':
            results = []
            for i, img in enumerate(images):
                aug_choice = random.choice(['rotate', 'flip', 'jitter', 'erase', 'none'])
                if aug_choice == 'rotate':
                    results.append(self.random_rotation(img))
                elif aug_choice == 'flip':
                    results.append(self.random_flip(img))
                elif aug_choice == 'jitter':
                    results.append(self.color_jitter(img))
                elif aug_choice == 'erase':
                    results.append(self.random_erasing(img))
                else:
                    results.append(img)
            return results
        else:
            return images


def get_augmentation_config() -> dict:
    """Get default augmentation configuration"""
    return {
        'rotation_enabled': True,
        'rotation_angle_range': (-15, 15),
        'flip_enabled': True,
        'flip_probability': 0.5,
        'scale_enabled': True,
        'scale_factor_range': (0.9, 1.1),
        'color_jitter_enabled': True,
        'jitter_intensity': 0.2,
        'cutout_enabled': True,
        'cutout_percentage': 0.3,
        'mixup_enabled': False,
        'mixup_alpha': 0.2,
        'cutmix_enabled': False,
        'cutmix_alpha': 1.0,
    }
