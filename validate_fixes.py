"""
Validation script for AutoFever code fixes and optimizations.
Tests the fixed code to ensure stability and effectiveness.
"""

import os
import sys
import time
import logging
import threading
import unittest
import weakref  # Added missing import
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add the src directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

# Import the fixed modules for testing
try:
    # Try to import the fixed modules
    from services.contact_manager_optimized_fixed import ContactManager, ContactGroup, Contact
    logger.info("Successfully imported fixed contact manager module")
except ImportError as e:
    logger.error(f"Error importing fixed modules: {str(e)}")
    sys.exit(1)

class TestContactManager(unittest.TestCase):
    """Test case for the fixed ContactManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.contact_manager = ContactManager()
        
    def test_create_group(self):
        """Test creating a contact group."""
        group = self.contact_manager.create_group("work", "Work Contacts")
        self.assertIsNotNone(group)
        self.assertEqual(group.id, "work")
        self.assertEqual(group.name, "Work Contacts")
        
    def test_add_contact_to_group(self):
        """Test adding a contact to a group."""
        contact = self.contact_manager.add_contact_to_group(
            "work", "john", "John Doe", "john@example.com", "123-456-7890"
        )
        self.assertIsNotNone(contact)
        self.assertEqual(contact.id, "john")
        self.assertEqual(contact.name, "John Doe")
        self.assertEqual(contact.email, "john@example.com")
        self.assertEqual(contact.phone, "123-456-7890")
        
    def test_get_contacts_in_group(self):
        """Test getting contacts in a group."""
        self.contact_manager.add_contact_to_group(
            "work", "john", "John Doe", "john@example.com", "123-456-7890"
        )
        self.contact_manager.add_contact_to_group(
            "work", "jane", "Jane Smith", "jane@example.com", "987-654-3210"
        )
        
        contacts = self.contact_manager.get_contacts_in_group("work")
        self.assertEqual(len(contacts), 2)
        
    def test_search_contacts(self):
        """Test searching for contacts."""
        # Add several contacts
        for i in range(10):
            self.contact_manager.add_contact_to_group(
                "work", f"user{i}", f"User {i}", f"user{i}@example.com", f"123-456-{i:04d}"
            )
            
        # Add a specific contact to search for
        self.contact_manager.add_contact_to_group(
            "work", "johndoe", "John Doe", "john@example.com", "555-123-4567"
        )
        
        # Search for the contact
        results = self.contact_manager.search_contacts("john")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, "johndoe")
        
    def test_thread_safety(self):
        """Test thread safety of the contact manager."""
        def add_contacts(group_id, start_idx, count):
            """Add contacts to a group."""
            for i in range(start_idx, start_idx + count):
                self.contact_manager.add_contact_to_group(
                    group_id, f"user{i}", f"User {i}", f"user{i}@example.com", f"123-456-{i:04d}"
                )
                
        def search_contacts(query):
            """Search for contacts."""
            return self.contact_manager.search_contacts(query)
            
        # Create threads to add contacts concurrently
        threads = []
        for i in range(5):
            t = threading.Thread(target=add_contacts, args=("work", i * 20, 20))
            threads.append(t)
            t.start()
            
        # Create threads to search contacts concurrently
        search_threads = []
        for i in range(5):
            t = threading.Thread(target=search_contacts, args=(f"User {i * 10}",))
            search_threads.append(t)
            t.start()
            
        # Wait for all threads to complete
        for t in threads:
            t.join()
            
        for t in search_threads:
            t.join()
            
        # Verify that all contacts were added
        contacts = self.contact_manager.get_contacts_in_group("work")
        self.assertEqual(len(contacts), 100)
        
    def test_export_import_json(self):
        """Test exporting and importing contacts as JSON."""
        # Add some contacts
        self.contact_manager.add_contact_to_group(
            "work", "john", "John Doe", "john@example.com", "123-456-7890"
        )
        self.contact_manager.add_contact_to_group(
            "family", "jane", "Jane Smith", "jane@example.com", "987-654-3210"
        )
        
        # Export to JSON
        json_data = self.contact_manager.export_to_json()
        
        # Create a new contact manager
        new_manager = ContactManager()
        
        # Import from JSON
        result = new_manager.import_from_json(json_data)
        self.assertTrue(result)
        
        # Verify imported data
        work_contacts = new_manager.get_contacts_in_group("work")
        family_contacts = new_manager.get_contacts_in_group("family")
        
        self.assertEqual(len(work_contacts), 1)
        self.assertEqual(len(family_contacts), 1)
        self.assertEqual(work_contacts[0].name, "John Doe")
        self.assertEqual(family_contacts[0].name, "Jane Smith")

class TestContactGroup(unittest.TestCase):
    """Test case for the fixed ContactGroup class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.group = ContactGroup("test", "Test Group")
        
    def test_add_contact(self):
        """Test adding a contact to the group."""
        contact = Contact("test", "Test User", "test@example.com", "123-456-7890")
        result = self.group.add_contact(contact)
        self.assertTrue(result)
        
    def test_get_contact(self):
        """Test getting a contact from the group."""
        contact = Contact("test", "Test User", "test@example.com", "123-456-7890")
        self.group.add_contact(contact)
        
        retrieved = self.group.get_contact("test")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, "test")
        self.assertEqual(retrieved.name, "Test User")
        
    def test_remove_contact(self):
        """Test removing a contact from the group."""
        contact = Contact("test", "Test User", "test@example.com", "123-456-7890")
        self.group.add_contact(contact)
        
        result = self.group.remove_contact("test")
        self.assertTrue(result)
        
        retrieved = self.group.get_contact("test")
        self.assertIsNone(retrieved)
        
    def test_thread_safety(self):
        """Test thread safety of the contact group."""
        def add_contacts(start_idx, count):
            """Add contacts to the group."""
            for i in range(start_idx, start_idx + count):
                contact = Contact(f"user{i}", f"User {i}", f"user{i}@example.com", f"123-456-{i:04d}")
                self.group.add_contact(contact)
                
        def remove_contacts(start_idx, count):
            """Remove contacts from the group."""
            for i in range(start_idx, start_idx + count):
                self.group.remove_contact(f"user{i}")
                
        # Create threads to add contacts concurrently
        add_threads = []
        for i in range(5):
            t = threading.Thread(target=add_contacts, args=(i * 20, 20))
            add_threads.append(t)
            t.start()
            
        # Wait for add threads to complete
        for t in add_threads:
            t.join()
            
        # Verify that all contacts were added
        contacts = self.group.get_all_contacts()
        self.assertEqual(len(contacts), 100)
        
        # Create threads to remove contacts concurrently
        remove_threads = []
        for i in range(5):
            t = threading.Thread(target=remove_contacts, args=(i * 20, 10))
            remove_threads.append(t)
            t.start()
            
        # Wait for remove threads to complete
        for t in remove_threads:
            t.join()
            
        # Verify that contacts were removed
        contacts = self.group.get_all_contacts()
        self.assertEqual(len(contacts), 50)

class TestContact(unittest.TestCase):
    """Test case for the fixed Contact class."""
    
    def test_contact_creation(self):
        """Test creating a contact."""
        contact = Contact("test", "Test User", "test@example.com", "123-456-7890", "Manager")
        self.assertEqual(contact.id, "test")
        self.assertEqual(contact.name, "Test User")
        self.assertEqual(contact.email, "test@example.com")
        self.assertEqual(contact.phone, "123-456-7890")
        self.assertEqual(contact.role, "Manager")
        
    def test_weak_reference_support(self):
        """Test weak reference support."""
        contact = Contact("test", "Test User", "test@example.com", "123-456-7890")
        weak_ref = weakref.ref(contact)
        
        # Verify that the weak reference works
        self.assertIsNotNone(weak_ref())
        self.assertEqual(weak_ref().id, "test")
        
        # Remove the strong reference
        del contact
        
        # Verify that the weak reference is now None
        self.assertIsNone(weak_ref())

def run_tests():
    """Run the test suite."""
    logger.info("Starting validation tests for fixed code")
    
    # Create a test suite
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    suite.addTest(loader.loadTestsFromTestCase(TestContactManager))
    suite.addTest(loader.loadTestsFromTestCase(TestContactGroup))
    suite.addTest(loader.loadTestsFromTestCase(TestContact))
    
    # Run the tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Log the results
    logger.info(f"Tests run: {result.testsRun}")
    logger.info(f"Errors: {len(result.errors)}")
    logger.info(f"Failures: {len(result.failures)}")
    
    # Return True if all tests passed, False otherwise
    return len(result.errors) == 0 and len(result.failures) == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
