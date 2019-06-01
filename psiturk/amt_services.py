# -*- coding: utf-8 -*-
""" This module is a facade for AMT (Boto) services. """

import boto3
import botocore
import datetime
import dateutil.tz

from flask import jsonify
import re as re
from psiturk.psiturk_config import PsiturkConfig

PERCENT_ASSIGNMENTS_APPROVED_QUAL_ID = '000000000000000000L0'
NUMBER_HITS_APPROVED_QUAL_ID = '00000000000000000040'
LOCALE_QUAL_ID = '00000000000000000071'
MASTERS_QUAL_ID = '2F1QJWKUDD8XADTFD2Q0G6UTO95ALH'
MASTERS_SANDBOX_QUAL_ID = '2ARFPLSP75KLA8M8DH1HTEQVJT3SY6'

NOTIFICATION_VERSION = '2006-05-05'

class MTurkHIT(object):
    ''' Structure for dealing with MTurk HITs '''

    def __init__(self, options):
        self.options = options

    def __repr__(self):
        return "%s \n\tStatus: %s \n\tHITid: %s \
            \n\tmax:%s/pending:%s/complete:%s/remain:%s \n\tCreated:%s \
            \n\tExpires:%s\n\tIs Expired:%s\n" % (
                self.options['title'],
                self.options['status'],
                self.options['hitid'],
                self.options['max_assignments'],
                self.options['number_assignments_pending'],
                self.options['number_assignments_completed'],
                self.options['number_assignments_available'],
                self.options['creation_time'],
                self.options['expiration'],
                self.options['is_expired']
            )

class MTurkServices(object):
    ''' MTurk services '''
    def __init__(self, aws_access_key_id, aws_secret_access_key, is_sandbox):
        self.update_credentials(aws_access_key_id, aws_secret_access_key)
        self.is_sandbox = is_sandbox
        self.setup_mturk_connection()
        self.valid_login = self.verify_aws_login()

        if not self.valid_login:
            print 'WARNING *****************************'
            print 'Sorry, AWS Credentials invalid.\nYou will only be able to '\
                  'test experiments locally until you enter\nvalid '\
                  'credentials in the AWS Access section of ~/.psiturkconfig\n'

    def update_credentials(self, aws_access_key_id, aws_secret_access_key):
        ''' Update credentials '''
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key

    def set_sandbox(self, is_sandbox):
        ''' Set sandbox '''
        self.is_sandbox = is_sandbox
        self.setup_mturk_connection()

    @staticmethod
    def _hit_xml_to_object(hits):
        hits_data = [MTurkHIT({
            'hitid': hit['HITId'],
            'title': hit['Title'],
            'status': hit['HITStatus'],
            'max_assignments': hit['MaxAssignments'],
            'number_assignments_completed': hit['NumberOfAssignmentsCompleted'],
            'number_assignments_pending': hit['NumberOfAssignmentsPending'],
            'number_assignments_available': hit['NumberOfAssignmentsAvailable'],
            'creation_time': hit['CreationTime'],
            'expiration': hit['Expiration'],
            'is_expired': datetime.datetime.now(hit['Expiration'].tzinfo) >= hit['Expiration']
        }) for hit in hits]
        return hits_data

    def get_all_hits(self):
        ''' Get all HITs '''
        if not self.connect_to_turk():
            return False
        try:
            hits = []
            paginator = self.mtc.get_paginator('list_hits')
            for page in paginator.paginate():
                hits.extend(page['HITs'])
        except Exception as e:
            raise e
        hits_data = self._hit_xml_to_object(hits)
        return hits_data

    def get_assignments(self, assignment_status=None, hit_ids=None):
        ''' Get workers '''
        if not self.connect_to_turk():
            return False
        try:
            if hit_ids and not isinstance(hit_ids, list):
                hit_ids = [hit_ids]
            else:
                hits = self.get_all_hits()
                hit_ids = [hit.options['hitid'] for hit in hits]

            assignments = []
            for hit_id in hit_ids:
                paginator = self.mtc.get_paginator('list_assignments_for_hit')
                args = dict(
                    HITId=hit_id
                )
                if assignment_status:
                    args['AssignmentStatuses'] = [assignment_status]

                for page in paginator.paginate(**args):
                    assignments.extend(page['Assignments'])

        except Exception as e:
            print e
            raise
        workers = [{
            'hitId': assignment['HITId'],
            'assignmentId': assignment['AssignmentId'],
            'workerId': assignment['WorkerId'],
            'submit_time': assignment['SubmitTime'],
            'accept_time': assignment['AcceptTime'],
            'status': assignment['AssignmentStatus'],
        } for assignment in assignments]
        return workers

    def get_assignment(self, assignment_id):
        if not self.connect_to_turk():
            return False
        try:
            assignment = self.mtc.get_assignment(AssignmentId=assignment_id)['Assignment']
        except Exception as e:
            return False
        worker_data = {
            'hitId': assignment['HITId'],
            'assignmentId': assignment['AssignmentId'],
            'workerId': assignment['WorkerId'],
            'submit_time': assignment['SubmitTime'],
            'accept_time': assignment['AcceptTime'],
            'status': assignment['AssignmentStatus'],
        }
        return worker_data

    def bonus_assignment(self, assignment_id, worker_id, amount, reason=""):
        ''' Bonus worker '''
        if not self.connect_to_turk():
            return False
        try:
            if not worker_id:
                assignment = self.mtc.get_assignment(AssignmentId=assignment_id)['Assignment']
                worker_id = assignment['WorkerId']
            self.mtc.send_bonus(WorkerId=worker_id, AssignmentId=assignment_id, BonusAmount=str(amount), Reason=reason)
            return True
        except Exception as e:
            import traceback
            traceback.print_stack()
            raise e
            return False

    def approve_assignment(self, assignment_id, override_rejection = False):
        ''' Approve worker '''
        if not self.connect_to_turk():
            return False
        try:
            self.mtc.approve_assignment(AssignmentId=assignment_id,
                OverrideRejection=override_rejection)
            return True
        except Exception as e:
            return False

    def reject_assignment(self, assignment_id):
        ''' Reject worker '''
        if not self.connect_to_turk():
            return False
        try:
            self.mtc.reject_assignment(AssignmentId=assignment_id, RequesterFeedback='')
            return True
        except Exception as e:
            print e
            return False

    def unreject_assignment(self, assignment_id):
        ''' Unreject worker '''
        return self.approve_assignment(assignment_id, override_rejection=True)

    def setup_mturk_connection(self):
        ''' Connect to turk '''
        if ((self.aws_access_key_id == 'YourAccessKeyId') or
                (self.aws_secret_access_key == 'YourSecretAccessKey')):
            print "AWS access key not set in ~/.psiturkconfig; please enter a valid access key."
            assert False

        if self.is_sandbox:
            endpoint_url = 'https://mturk-requester-sandbox.us-east-1.amazonaws.com'
        else:
            endpoint_url = 'https://mturk-requester.us-east-1.amazonaws.com'

        self.mtc = boto3.client('mturk',
                region_name='us-east-1',
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                endpoint_url=endpoint_url)
        return True

    def verify_aws_login(self):
        ''' Verify AWS login '''
        if not self.mtc:
            return False

        try:
            self.mtc.get_account_balance()
        except Exception as exception:
            print exception
            return False
        else:
            return True

    def connect_to_turk(self):
        ''' Connect to turk '''
        if not self.valid_login or not self.mtc:
            print 'Sorry, unable to connect to Amazon Mechanical Turk. AWS '\
                  'credentials invalid.'
            return False

        return True

    def configure_hit(self, hit_config):
        ''' Configure HIT '''

        # Qualification:
        quals = []
        quals.append(dict(
            QualificationTypeId=PERCENT_ASSIGNMENTS_APPROVED_QUAL_ID,
            Comparator='GreaterThanOrEqualTo',
            IntegerValues=[int(hit_config['approve_requirement'])]
        ))

        quals.append(dict(
            QualificationTypeId=NUMBER_HITS_APPROVED_QUAL_ID,
            Comparator='GreaterThanOrEqualTo',
            IntegerValues=[int(hit_config['number_hits_approved'])]
        ))

        if hit_config['require_master_workers']:
            master_qualId = MASTERS_SANDBOX_QUAL_ID if self.is_sandbox else MASTERS_QUAL_ID
            quals.append(dict(
                QualificationTypeId=master_qualId,
                Comparator='Exists'
            ))

        if hit_config['us_only']:
            quals.append(dict(
                QualificationTypeId=LOCALE_QUAL_ID,
                Comparator='EqualTo',
                LocaleValues=[{'Country': 'US'}]
            ))

        # Create a HIT type for this HIT.
        hit_type = self.mtc.create_hit_type(
            Title=hit_config['title'],
            Description=hit_config['description'],
            Reward=str(hit_config['reward']),
            AssignmentDurationInSeconds=int(hit_config['duration'].total_seconds()),
            Keywords=hit_config['keywords'],
            QualificationRequirements=quals)

        # Check the config file to see if notifications are wanted.
        config = PsiturkConfig()
        config.load_config()

        try:
            url = config.get('Server Parameters', 'notification_url')

            all_event_types = [
                "AssignmentAccepted",
                "AssignmentAbandoned",
                "AssignmentReturned",
                "AssignmentSubmitted",
                "HITReviewable",
                "HITExpired",
            ]

            # TODO: not sure if this works. Can't find documentation in PsiTurk or MTurk
            self.mtc.update_notification_settings(
                HitTypeId=hit_type['HITTypeId'],
                Notification=dict(
                    Destination=url,
                    Transport='REST',
                    Version=NOTIFICATION_VERSION,
                    EventTypes=all_event_types,
                ),
            )

        except Exception as e:
            pass

        schema_url = "http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd"
        template = '<ExternalQuestion xmlns="%(schema_url)s"><ExternalURL>%%(external_url)s</ExternalURL><FrameHeight>%%(frame_height)s</FrameHeight></ExternalQuestion>' % vars()
        question = template % dict(
            external_url=hit_config['ad_location'],
            frame_height=600,
        )


        # Specify all the HIT parameters
        self.param_dict = dict(
            HITTypeId=hit_type['HITTypeId'],
            Question=question,
            LifetimeInSeconds=int(hit_config['lifetime'].total_seconds()),
            MaxAssignments=hit_config['max_assignments'],
            # TODO
            # ResponseGroups=[
            #     'Minimal',
            #     'HITDetail',
            #     'HITQuestion',
            #     'HITAssignmentSummary'
            # ]
            )

    def check_balance(self):
        ''' Check balance '''
        if not self.connect_to_turk():
            return '-'
        return self.mtc.get_account_balance()['AvailableBalance']

    # TODO (if valid AWS credentials haven't been provided then
    # connect_to_turk() will fail, not error checking here and elsewhere)
    def create_hit(self, hit_config):
        ''' Create HIT '''
        try:
            if not self.connect_to_turk():
                return False
            self.configure_hit(hit_config)
            myhit = self.mtc.create_hit_with_hit_type(**self.param_dict)['HIT']
            hitid = myhit['HITId']
        except Exception as e:
            print e
            return False
        else:
            return hitid

    # TODO(Jay): Have a wrapper around functions that serializes them.
    # Default output should not be serialized.
    def expire_hit(self, hitid):
        ''' Expire HIT '''
        if not self.connect_to_turk():
            return False
        try:
            self.mtc.update_expiration_for_hit(
                HITId=hitid,
                ExpireAt=datetime.datetime.now()
            )
            return True
        except Exception as e:
            print "Failed to expire HIT. Please check the ID and try again."
            print e
            return False

    def delete_hit(self, hitid):
        ''' Delete HIT '''
        if not self.connect_to_turk():
            return False
        try:
            self.mtc.delete_hit(HITId=hitid)
        except Exception, e:
            print "Failed to delete of HIT %s. Make sure there are no "\
                "assignments remaining to be reviewed." % hitid

    def extend_hit(self, hitid, assignments_increment=None,
                   expiration_increment=None):
        if not self.connect_to_turk():
            return False
        try:
            if assignments_increment:
                self.mtc.create_additional_assignments_for_hit(HITId=hitid,
                    NumberOfAdditionalAssignments=int(assignments_increment))

            if expiration_increment:
                hit = self.get_hit(hitid)
                print 'got hit', hit
                expiration = hit['Expiration'] + datetime.timedelta(minutes=int(expiration_increment))
                self.mtc.update_expiration_for_hit(HITId=hitid, ExpireAt=expiration)

            return True
        except Exception, e:
            print e
            print "Failed to extend HIT %s. Please check the ID and try again." \
                % hitid
            return False

    def get_hit(self, hitid):
        ''' Get HIT '''
        if not self.connect_to_turk():
            return False
        try:
            hitdata = self.mtc.get_hit(HITId=hitid)
        except Exception as e:
            print e
            return False
        return hitdata['HIT']

    def get_hit_status(self, hitid):
        ''' Get HIT status '''
        hitdata = self.get_hit(hitid)
        if not hitdata:
            return False

        return hitdata['HITStatus']

    def get_summary(self):
        ''' Get summary '''
        try:
            balance = self.check_balance()
            summary = jsonify(balance=str(balance))
            return summary
        except MTurkRequestError as exception:
            print exception.error_message
            return False

