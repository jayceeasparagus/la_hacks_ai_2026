"""One shared demo configuration for examples, replay and synthetic evaluation."""

from app.models import Camera, Rule, Zone


def demo_cameras() -> list[Camera]:
    return [Camera(id='cam_entrance', name='Main entrance', source='webcam:0'),
            Camera(id='cam_exit', name='Emergency exit', source='webcam:1')]


def demo_zones() -> list[Zone]:
    polygon = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.9), (0.2, 0.9)]
    return [Zone(id='main_entrance', camera_id='cam_entrance', name='Main entrance',
                 polygon=polygon),
            Zone(id='emergency_exit', camera_id='cam_exit', name='Emergency exit',
                 polygon=polygon)]


def demo_rules() -> list[Rule]:
    return [
        Rule(id='clear_bag', name='Clear-bag policy', type='object_attribute',
             objects=['backpack', 'handbag', 'suitcase'], zone='main_entrance',
             attribute={'name': 'transparent', 'expected': True},
             duration_seconds=1, severity='review'),
        Rule(id='pro_camera', name='Camera policy', type='object_attribute',
             objects=['camera'], zone='main_entrance',
             attribute={'name': 'professional', 'expected': False},
             duration_seconds=1, severity='review'),
        Rule(id='blocked_exit', name='Exit obstruction', type='persistent_object',
             objects=['backpack', 'handbag', 'suitcase', 'chair'],
             zone='emergency_exit', duration_seconds=5, severity='urgent'),
    ]
