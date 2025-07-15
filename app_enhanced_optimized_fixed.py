"""
Enhanced AutoFever - Main application with optimized resource usage
Implements all user experience enhancements with efficiency optimizations
"""

import os
import json
import time
import threading
import logging
from datetime import datetime, timedelta  # Fixed: Added timedelta import
from functools import lru_cache
import weakref

# Import optimized models
from models.contact_optimized import Contact, ContactGroup
from models.message_template_optimized import MessageTemplate
from models.notification_optimized import Notification

# Import optimized services
from services.contact_manager_optimized import ContactManager
from services.template_manager_optimized import TemplateManager
from services.notification_controller import NotificationController
from services.recovery_tracker import RecoveryTracker
from services.ai_contact_suggestion_optimized import MessageAnalyzer, SuggestionLearner, PrivacyManager

# Import enhanced services
from services.onboarding_service import OnboardingWizard, ContactImporter
from services.smart_notification_service import SmartNotificationService, RecoveryReminderService
from services.accessibility_service import AccessibilityService, VoiceControlService, KeyboardNavigationService
from services.personalization_service import PersonalizationService, TemplatePersonalizationService
from services.feedback_service import FeedbackService, RecipientFeedbackService
from services.offline_support_service import OfflineSupportService, LowBandwidthService, DataPersistenceService

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("autofever.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class AutoFeverApp:
    """
    Main application class for AutoFever with enhanced features and optimized resource usage.
    """
    
    def __init__(self):
        """Initialize the AutoFever application."""
        # Initialize core services with optimized implementations
        self.contact_manager = ContactManager()
        self.template_manager = TemplateManager()
        self.notification_controller = NotificationController()
        self.recovery_tracker = RecoveryTracker()
        
        # Initialize AI services with optimized implementations
        self.privacy_manager = PrivacyManager()
        self.message_analyzer = MessageAnalyzer()
        self.suggestion_learner = SuggestionLearner()
        
        # Initialize enhanced services
        self._init_enhanced_services()
        
        # Application state
        self.app_state = {
            'current_view': 'home',
            'user_authenticated': False,
            'setup_completed': False,
            'illness_active': False,
            'last_activity': datetime.now().isoformat()
        }
        
        # Resource monitoring
        self.resource_usage = {
            'memory_usage': 0,
            'cpu_usage': 0,
            'battery_impact': 'low',
            'last_checked': datetime.now().isoformat()
        }
        
        # Thread synchronization
        self._state_lock = threading.RLock()  # Added lock for thread safety
        
        # Start background services
        self._start_background_services()
        
        logger.info("AutoFever application initialized")
    
    def _init_enhanced_services(self):
        """Initialize enhanced services with optimized resource usage."""
        # Onboarding services
        self.onboarding_wizard = OnboardingWizard(self.contact_manager, self.template_manager)
        self.contact_importer = ContactImporter(self.contact_manager)
        
        # Smart notification services
        self.smart_notification_service = SmartNotificationService(self.notification_controller, self.recovery_tracker)
        self.recovery_reminder_service = RecoveryReminderService(self.recovery_tracker)
        
        # Accessibility services
        self.accessibility_service = AccessibilityService()
        self.voice_control_service = VoiceControlService(self)
        self.keyboard_navigation_service = KeyboardNavigationService()
        
        # Personalization services
        self.personalization_service = PersonalizationService(self.template_manager)
        self.template_personalization_service = TemplatePersonalizationService(self.template_manager)
        
        # Feedback services
        self.feedback_service = FeedbackService(self.notification_controller)
        self.recipient_feedback_service = RecipientFeedbackService(self.feedback_service)
        
        # Offline support services
        self.offline_support_service = OfflineSupportService(self.notification_controller)
        self.low_bandwidth_service = LowBandwidthService()
        self.data_persistence_service = DataPersistenceService()
    
    def _start_background_services(self):
        """Start background services with optimized resource usage."""
        try:
            # Start smart notification service
            self.smart_notification_service.start_notification_service()
            
            # Start offline support services
            self.offline_support_service.start_sync_service()
            self.data_persistence_service.start_auto_save()
            
            # Initialize AI models
            self.message_analyzer.initialize_models()
            
            # Schedule periodic resource monitoring
            self._schedule_resource_monitoring()
            
            logger.info("Background services started successfully")
        except Exception as e:
            logger.error(f"Error starting background services: {str(e)}")
            raise
    
    def _schedule_resource_monitoring(self):
        """Schedule periodic resource monitoring."""
        def monitor_resources():
            while True:
                try:
                    self._update_resource_usage()
                    time.sleep(300)  # Check every 5 minutes
                except Exception as e:
                    logger.error(f"Error in resource monitoring: {str(e)}")
                    time.sleep(60)  # Shorter retry interval on error
        
        # Start monitoring thread
        monitor_thread = threading.Thread(target=monitor_resources)
        monitor_thread.daemon = True
        monitor_thread.start()
    
    def _update_resource_usage(self):
        """Update resource usage statistics."""
        # In a real implementation, this would measure actual resource usage
        # For the prototype, we'll use simulated values
        with self._state_lock:  # Thread safety
            self.resource_usage = {
                'memory_usage': 50,  # MB
                'cpu_usage': 2,      # %
                'battery_impact': 'low',
                'last_checked': datetime.now().isoformat()
            }
    
    def start_onboarding(self):
        """Start the onboarding process."""
        try:
            return self.onboarding_wizard.start_wizard()
        except Exception as e:
            logger.error(f"Error starting onboarding: {str(e)}")
            return {"error": "Failed to start onboarding", "details": str(e)}
    
    def complete_onboarding(self):
        """Complete the onboarding process."""
        try:
            with self._state_lock:  # Thread safety
                self.app_state['setup_completed'] = True
            
            # Save user data for offline use
            self.data_persistence_service.save_data('user_data', {
                'setup_completed': True,
                'setup_time': datetime.now().isoformat()
            })
            
            # Cache data for offline use
            self._cache_data_for_offline()
            
            return {"success": True}
        except Exception as e:
            logger.error(f"Error completing onboarding: {str(e)}")
            return {"error": "Failed to complete onboarding", "details": str(e)}
    
    def _cache_data_for_offline(self):
        """Cache data for offline use."""
        try:
            # Cache contacts
            contacts_data = {}
            for group in self.contact_manager.get_all_groups():
                contacts_data[group.id] = {
                    'name': group.name,
                    'contacts': [
                        {
                            'id': contact.id,
                            'name': contact.name,
                            'role': contact.role,
                            'email': contact.email,
                            'phone': contact.phone
                        }
                        for contact in group.get_all_contacts()
                    ]
                }
            self.offline_support_service.cache_contacts(contacts_data)
            
            # Cache templates
            templates_data = {}
            for template in self.template_manager.get_all_templates():
                templates_data[template.id] = {
                    'title': template.title,
                    'content': template.content
                }
            self.offline_support_service.cache_templates(templates_data)
            
            # Cache settings
            settings_data = {
                'accessibility': self.accessibility_service.get_settings(),
                'personalization': self.personalization_service.get_preferences(),
                'smart_notifications': {
                    'quiet_hours': self.smart_notification_service.quiet_hours
                }
            }
            self.offline_support_service.cache_settings(settings_data)
            
            # Save to persistent storage
            self.data_persistence_service.save_data('contacts', contacts_data)
            self.data_persistence_service.save_data('templates', templates_data)
            self.data_persistence_service.save_data('settings', settings_data)
            self.data_persistence_service.save_all_data()
            
            logger.info("Data cached successfully for offline use")
        except Exception as e:
            logger.error(f"Error caching data for offline use: {str(e)}")
            raise
    
    # Refactored to reduce code duplication
    def _process_notification(self, is_illness, severity=None, duration=None, custom_message=None):
        """
        Process illness or recovery notification with shared logic.
        
        Args:
            is_illness: True for illness notification, False for recovery
            severity: Severity of the illness (for illness notifications)
            duration: Expected duration (for illness notifications)
            custom_message: Custom message
            
        Returns:
            dict: Result of notification
        """
        # For recovery, check if illness is active
        if not is_illness and not self.app_state['illness_active']:
            return {
                'success': False,
                'message': 'No active illness to recover from'
            }
            
        # Check if we're online
        if not self.offline_support_service.get_sync_status()['connectivity']:
            # We're offline, queue the notification
            if is_illness:
                context = {
                    'severity': severity or 'moderate',
                    'duration': duration or '1-2 days',
                    'return_date': (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d'),
                    'custom_message': custom_message or '',
                    'user_name': 'User'  # Would be actual user name in real implementation
                }
            else:  # Recovery
                context = {
                    'recovery_message': custom_message or 'I am feeling better now and will be returning to normal activities.',
                    'user_name': 'User'  # Would be actual user name in real implementation
                }
            
            # Queue notification
            notification_id = self.offline_support_service.queue_notification(
                self.contact_manager,
                self.template_manager,
                ['work', 'family'],  # Default groups
                context
            )
            
            # Update app state
            with self._state_lock:  # Thread safety
                self.app_state['illness_active'] = is_illness
            
            # Start or end tracking illness
            if is_illness:
                self.recovery_tracker.start_tracking(severity)
            else:
                illness_data = self.recovery_tracker.end_tracking()
                # Record for statistics
                if illness_data:
                    self.feedback_service.record_illness(
                        illness_data['start_time'],
                        illness_data['end_time'],
                        illness_data['severity']
                    )
            
            return {
                'success': True,
                'offline': True,
                'queued': True,
                'notification_id': notification_id
            }
        else:
            # We're online, send notification immediately
            if is_illness:
                context = {
                    'severity': severity or 'moderate',
                    'duration': duration or '1-2 days',
                    'return_date': (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d'),
                    'custom_message': custom_message or '',
                    'user_name': 'User'  # Would be actual user name in real implementation
                }
                
                # Send notification
                notification_id = self.notification_controller.send_notifications(
                    self.contact_manager,
                    self.template_manager,
                    ['work', 'family'],  # Default groups
                    context
                )
            else:  # Recovery
                context = {
                    'recovery_message': custom_message or 'I am feeling better now and will be returning to normal activities.',
                    'user_name': 'User'  # Would be actual user name in real implementation
                }
                
                # Send notification
                notification_id = self.notification_controller.send_recovery_notifications(
                    self.contact_manager,
                    self.template_manager,
                    ['work', 'family'],  # Default groups
                    context
                )
            
            # Update app state
            with self._state_lock:  # Thread safety
                self.app_state['illness_active'] = is_illness
            
            # Start or end tracking illness
            if is_illness:
                self.recovery_tracker.start_tracking(severity)
            else:
                illness_data = self.recovery_tracker.end_tracking()
                # Record for statistics
                if illness_data:
                    self.feedback_service.record_illness(
                        illness_data['start_time'],
                        illness_data['end_time'],
                        illness_data['severity']
                    )
            
            # Record for statistics
            self.feedback_service.record_notification_sent(
                notification_id,
                self._count_recipients(['work', 'family'])
            )
            
            return {
                'success': True,
                'offline': False,
                'notification_id': notification_id
            }
    
    def activate_illness(self, severity=None, duration=None, custom_message=None):
        """
        Activate illness notification.
        
        Args:
            severity: Severity of the illness
            duration: Expected duration
            custom_message: Custom message
            
        Returns:
            dict: Result of activation
        """
        try:
            return self._process_notification(True, severity, duration, custom_message)
        except Exception as e:
            logger.error(f"Error activating illness: {str(e)}")
            return {"error": "Failed to activate illness", "details": str(e)}
    
    def activate_recovery(self, custom_message=None):
        """
        Activate recovery notification.
        
        Args:
            custom_message: Custom message
            
        Returns:
            dict: Result of activation
        """
        try:
            return self._process_notification(False, custom_message=custom_message)
        except Exception as e:
            logger.error(f"Error activating recovery: {str(e)}")
            return {"error": "Failed to activate recovery", "details": str(e)}
    
    def _count_recipients(self, group_ids):
        """
        Count recipients in specified groups.
        
        Args:
            group_ids: List of group IDs
            
        Returns:
            int: Number of recipients
        """
        count = 0
        for group_id in group_ids:
            group = self.contact_manager.get_group(group_id)
            if group:
                count += len(group.get_all_contacts())
        return count
    
    def show_contacts(self):
        """Show contacts page."""
        with self._state_lock:  # Thread safety
            self.app_state['current_view'] = 'contacts'
            self.app_state['last_activity'] = datetime.now().isoformat()
        return {'view': 'contacts'}
    
    def show_templates(self):
        """Show templates page."""
        with self._state_lock:  # Thread safety
            self.app_state['current_view'] = 'templates'
            self.app_state['last_activity'] = datetime.now().isoformat()
        return {'view': 'templates'}
    
    def show_settings(self):
        """Show settings page."""
        with self._state_lock:  # Thread safety
            self.app_state['current_view'] = 'settings'
            self.app_state['last_activity'] = datetime.now().isoformat()
        return {'view': 'settings'}
    
    def show_home(self):
        """Show home page."""
        with self._state_lock:  # Thread safety
            self.app_state['current_view'] = 'home'
            self.app_state['last_activity'] = datetime.now().isoformat()
        return {'view': 'home'}
    
    def show_help(self):
        """Show help page."""
        with self._state_lock:  # Thread safety
            self.app_state['current_view'] = 'help'
            self.app_state['last_activity'] = datetime.now().isoformat()
        return {'view': 'help'}
    
    def get_app_state(self):
        """
        Get current application state.
        
        Returns:
            dict: Current application state
        """
        with self._state_lock:  # Thread safety
            return self.app_state.copy()
    
    def get_resource_usage(self):
        """
        Get current resource usage.
        
        Returns:
            dict: Resource usage statistics
        """
        with self._state_lock:  # Thread safety
            return self.resource_usage.copy()
    
    def optimize_resources(self):
        """
        Optimize resource usage based on current state.
        
        Returns:
            dict: Optimization results
        """
        try:
            results = {
                'optimizations_applied': [],
                'memory_saved': 0,
                'cpu_saved': 0
            }
            
            # Check if app is in background
            if self._is_app_in_background():
                # Pause non-essential services
                self.voice_control_service.stop_listening()
                results['optimizations_applied'].append('paused_voice_control')
                results['cpu_saved'] += 1
                
                # Reduce sync frequency
                # In a real implementation, this would adjust sync intervals
                results['optimizations_applied'].append('reduced_sync_frequency')
                results['cpu_saved'] += 0.5
            
            # Check if low battery
            if self._is_low_battery():
                # Enable low bandwidth mode
                self.low_bandwidth_service.enable_low_bandwidth_mode()
                results['optimizations_applied'].append('enabled_low_bandwidth_mode')
                results['cpu_saved'] += 1
                results['memory_saved'] += 10
            
            # Clear caches if memory pressure
            if self._is_memory_pressure():
                # Clear non-essential caches
                self._clear_non_essential_caches()
                results['optimizations_applied'].append('cleared_caches')
                results['memory_saved'] += 20
            
            return results
        except Exception as e:
            logger.error(f"Error optimizing resources: {str(e)}")
            return {"error": "Failed to optimize resources", "details": str(e)}
    
    def _is_app_in_background(self):
        """
        Check if app is in background.
        
        Returns:
            bool: True if in background, False otherwise
        """
        # In a real implementation, this would check actual app state
        # For the prototype, we'll check last activity time
        with self._state_lock:  # Thread safety
            last_activity = datetime.fromisoformat(self.app_state['last_activity'])
        return (datetime.now() - last_activity).total_seconds() > 300  # 5 minutes
    
    def _is_low_battery(self):
        """
        Check if device has low battery.
        
        Returns:
            bool: True if low battery, False otherwise
        """
        # In a real implementation, this would check actual battery level
        # For the prototype, we'll return False
        return False
    
    def _is_memory_pressure(self):
        """
        Check if device is under memory pressure.
        
        Returns:
            bool: True if under memory pressure, False otherwise
        """
        # In a real implementation, this would check actual memory usage
        # For the prototype, we'll return False
        return False
    
    def _clear_non_essential_caches(self):
        """Clear non-essential caches to free memory."""
        try:
            # Clear template rendering cache
            if hasattr(self.template_manager, '_render_cache'):
                self.template_manager._render_cache.clear()
            
            # Clear analysis cache
            if hasattr(self.message_analyzer, '_analysis_cache'):
                self.message_analyzer._analysis_cache.clear()
            
            # Clear stats cache
            if hasattr(self.feedback_service, '_stats_cache'):
                self.feedback_service._stats_cache.clear()
            
            # Force garbage collection
            import gc
            gc.collect()
            
            logger.info("Non-essential caches cleared successfully")
        except Exception as e:
            logger.error(f"Error clearing caches: {str(e)}")
            raise
    
    def shutdown(self):
        """Shutdown the application."""
        try:
            # Stop background services
            self.smart_notification_service.stop_notification_service()
            self.offline_support_service.stop_sync_service()
            self.data_persistence_service.stop_auto_save()
            
            # Save all data
            self.data_persistence_service.save_all_data()
            
            logger.info("Application shutdown completed successfully")
            return {'success': True}
        except Exception as e:
            logger.error(f"Error during shutdown: {str(e)}")
            return {"error": "Failed to shutdown properly", "details": str(e)}


# Flask application factory
def create_app():
    """Create Flask application."""
    from flask import Flask, render_template, request, jsonify, abort
    
    app = Flask(__name__)
    autofever = AutoFeverApp()
    
    @app.route('/')
    def index():
        """Render index page."""
        return render_template('index.html')
    
    @app.route('/api/state')
    def get_state():
        """Get application state."""
        return jsonify(autofever.get_app_state())
    
    @app.route('/api/activate-illness', methods=['POST'])
    def activate_illness():
        """Activate illness notification."""
        try:
            data = request.json or {}
            # Input validation
            if not isinstance(data, dict):
                abort(400, description="Invalid request data")
                
            severity = data.get('severity')
            duration = data.get('duration')
            custom_message = data.get('custom_message')
            
            # Validate inputs
            if severity and not isinstance(severity, str):
                abort(400, description="Invalid severity value")
            if duration and not isinstance(duration, str):
                abort(400, description="Invalid duration value")
            if custom_message and not isinstance(custom_message, str):
                abort(400, description="Invalid custom message")
                
            result = autofever.activate_illness(severity, duration, custom_message)
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error in activate-illness endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/activate-recovery', methods=['POST'])
    def activate_recovery():
        """Activate recovery notification."""
        try:
            data = request.json or {}
            # Input validation
            if not isinstance(data, dict):
                abort(400, description="Invalid request data")
                
            custom_message = data.get('custom_message')
            
            # Validate inputs
            if custom_message and not isinstance(custom_message, str):
                abort(400, description="Invalid custom message")
                
            result = autofever.activate_recovery(custom_message)
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error in activate-recovery endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/contacts')
    def get_contacts():
        """Get contacts."""
        try:
            groups = []
            for group in autofever.contact_manager.get_all_groups():
                groups.append({
                    'id': group.id,
                    'name': group.name,
                    'contacts': [
                        {
                            'id': contact.id,
                            'name': contact.name,
                            'role': contact.role,
                            'email': contact.email,
                            'phone': contact.phone
                        }
                        for contact in group.get_all_contacts()
                    ]
                })
            return jsonify(groups)
        except Exception as e:
            logger.error(f"Error in contacts endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/templates')
    def get_templates():
        """Get templates."""
        try:
            templates = []
            for template in autofever.template_manager.get_all_templates():
                templates.append({
                    'id': template.id,
                    'title': template.title,
                    'content': template.content
                })
            return jsonify(templates)
        except Exception as e:
            logger.error(f"Error in templates endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/settings', methods=['GET', 'POST'])
    def settings():
        """Get or update settings."""
        try:
            if request.method == 'POST':
                data = request.json
                
                # Input validation
                if not isinstance(data, dict):
                    abort(400, description="Invalid request data")
                
                # Update accessibility settings
                if 'accessibility' in data:
                    if not isinstance(data['accessibility'], dict):
                        abort(400, description="Invalid accessibility settings")
                    autofever.accessibility_service.update_settings(data['accessibility'])
                    
                # Update personalization settings
                if 'personalization' in data:
                    if not isinstance(data['personalization'], dict):
                        abort(400, description="Invalid personalization settings")
                    autofever.personalization_service.update_preferences(data['personalization'])
                    
                # Update quiet hours settings
                if 'quiet_hours' in data:
                    if not isinstance(data['quiet_hours'], dict):
                        abort(400, description="Invalid quiet hours settings")
                    autofever.smart_notification_service.update_quiet_hours(
                        data['quiet_hours'].get('start', 22),
                        data['quiet_hours'].get('end', 7),
                        data['quiet_hours'].get('enabled', True)
                    )
                    
                # Update low bandwidth settings
                if 'low_bandwidth' in data:
                    if not isinstance(data['low_bandwidth'], dict):
                        abort(400, description="Invalid low bandwidth settings")
                    if data['low_bandwidth'].get('enabled', False):
                        autofever.low_bandwidth_service.enable_low_bandwidth_mode()
                    else:
                        autofever.low_bandwidth_service.disable_low_bandwidth_mode()
                        
                    if 'optimization_settings' in data['low_bandwidth']:
                        if not isinstance(data['low_bandwidth']['optimization_settings'], dict):
                            abort(400, description="Invalid optimization settings")
                        autofever.low_bandwidth_service.update_optimization_settings(
                            data['low_bandwidth']['optimization_settings']
                        )
                
                return jsonify({'success': True})
            else:
                return jsonify({
                    'accessibility': autofever.accessibility_service.get_settings(),
                    'personalization': autofever.personalization_service.get_preferences(),
                    'quiet_hours': autofever.smart_notification_service.quiet_hours,
                    'low_bandwidth': {
                        'enabled': autofever.low_bandwidth_service.is_low_bandwidth_mode(),
                        'optimization_settings': autofever.low_bandwidth_service.get_optimization_settings()
                    }
                })
        except Exception as e:
            logger.error(f"Error in settings endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/statistics')
    def get_statistics():
        """Get usage statistics."""
        try:
            return jsonify(autofever.feedback_service.get_usage_statistics())
        except Exception as e:
            logger.error(f"Error in statistics endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/resource-usage')
    def get_resource_usage():
        """Get resource usage."""
        try:
            return jsonify(autofever.get_resource_usage())
        except Exception as e:
            logger.error(f"Error in resource-usage endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/optimize-resources')
    def optimize_resources():
        """Optimize resource usage."""
        try:
            return jsonify(autofever.optimize_resources())
        except Exception as e:
            logger.error(f"Error in optimize-resources endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/acknowledge/<token>')
    def acknowledge(token):
        """Acknowledge notification."""
        try:
            # Validate token
            if not token or not isinstance(token, str) or len(token) < 8:
                abort(400, description="Invalid token")
                
            # Check if token exists
            if not autofever.feedback_service.token_exists(token):
                abort(404, description="Token not found")
                
            return render_template('acknowledge.html', token=token)
        except Exception as e:
            logger.error(f"Error in acknowledge endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/acknowledge', methods=['POST'])
    def process_acknowledgment():
        """Process acknowledgment."""
        try:
            data = request.json
            
            # Input validation
            if not isinstance(data, dict):
                abort(400, description="Invalid request data")
                
            token = data.get('token')
            response = data.get('response')
            
            # Validate inputs
            if not token or not isinstance(token, str):
                abort(400, description="Invalid token")
            if response is not None and not isinstance(response, str):
                abort(400, description="Invalid response")
                
            result = autofever.feedback_service.process_acknowledgment(token, response)
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error in process-acknowledgment endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/voice-command', methods=['POST'])
    def voice_command():
        """Process voice command."""
        try:
            data = request.json
            
            # Input validation
            if not isinstance(data, dict):
                abort(400, description="Invalid request data")
                
            text = data.get('text', '')
            
            # Validate inputs
            if not isinstance(text, str):
                abort(400, description="Invalid text")
                
            result = autofever.voice_control_service.process_voice_input(text)
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error in voice-command endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    @app.route('/api/sync-status')
    def sync_status():
        """Get sync status."""
        try:
            return jsonify(autofever.offline_support_service.get_sync_status())
        except Exception as e:
            logger.error(f"Error in sync-status endpoint: {str(e)}")
            return jsonify({"error": str(e)}), 500
    
    # Error handlers
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": str(e.description)}), 400
        
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Resource not found"}), 404
        
    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "Internal server error"}), 500
    
    return app


# Run the application
if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
