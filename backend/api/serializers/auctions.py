from django.db import transaction
from django.utils import timezone

from rest_framework import serializers
from rest_framework.exceptions import ParseError

from auction.constants import AUCTION_STATUS_OPEN
from auction.constants import BID_STATUS_ACTIVE
from auction.constants import BID_STATUS_REJECTED
from auction.models import Auction
from auction.models import Bid
from auction.models import Sale
from api.serializers.auth import UserSerializer
from api.serializers.entities import ProductSerializer
from api.serializers.entities import ProductDetailSerializer
from api.serializers.mixins import TagnamesSerializerMixin
from history.constants import HISTORY_RECORD_AUCTION_NEW
from history.constants import HISTORY_RECORD_USER_BID
from history.models import HistoryRecord
from notification.constants import NOTIFICATION_AUCTION_NEW_BID
from notification.email import send_email
from notification.models import Notification


class AuctionSerializer(serializers.ModelSerializer):
    product_details = serializers.SerializerMethodField()

    class Meta:
        model = Auction
        fields = (
            'pk',
            'title', 'starting_price', 'product',
            'current_price', 'status', 'started_at', 'open_until', 'ended_at', 'product_details'
        )
        read_only_fields = ('pk', 'current_price', 'status', 'started_at', 'ended_at', 'product_details')

    def get_product_details(self, obj):
        serializer = ProductDetailSerializer(obj.product)
        return serializer.data


class AuctionAdminSerializer(AuctionSerializer):
    """
    Serializer used for Admin AuctionListView and AuctionDetailView
    """
    highest_bidder = serializers.SerializerMethodField()

    class Meta:
        model = Auction
        fields = AuctionSerializer.Meta.fields + (
            'charity', 'max_bid', 'min_bid', 'highest_bidder', 'number_of_bids', 'time_remaining'
        )
        read_only_fields = (
            'pk', 'current_price', 'started_at', 'ended_at', 'product_details',
            'max_bid', 'min_bid', 'highest_bidder', 'number_of_bids', 'time_remaining',
        )

    def get_highest_bidder(self, obj):
        try:
            user = obj.highest_bid.user
            return user.email
        except:
            return None

    def create(self, *args, **kwargs):
        instance = super(AuctionAdminSerializer, self).create(*args, **kwargs)
        HistoryRecord.objects.create_history_record(instance, None, HISTORY_RECORD_AUCTION_NEW)
        return instance


class AuctionDetailWithSimilarSerializer(serializers.ModelSerializer):
    """
    Serializer used in front api for serializing Auction model object, with data on similar auctions
    """
    product = ProductDetailSerializer(read_only=True)
    similar_auctions = AuctionSerializer(many=True, read_only=True)
    donor_auctions = AuctionSerializer(many=True, read_only=True)

    class Meta:
        model = Auction
        fields = (
            'pk', 'title', 'starting_price', 'current_price', 'status',
            'started_at', 'open_until', 'ended_at',
            'product', 'similar_auctions', 'donor_auctions')
        read_only_fields = (
            'pk', 'title', 'starting_price', 'current_price', 'status',
            'started_at', 'open_until', 'ended_at',
            'product', 'similar_auctions', 'donor_auctions')


class StartAuctionSerializer(serializers.Serializer):
    open_until = serializers.DateTimeField(required=False)
    duration_days = serializers.IntegerField(required=False, min_value=0)
    duration_hours = serializers.IntegerField(required=False, min_value=0)
    duration_minutes = serializers.IntegerField(required=False, min_value=0)

    def validate(self, data):
        data = super(StartAuctionSerializer, self).validate(data)

        if ('open_until' not in data and
                'duration_days' not in data and
                'duration_hours' not in data and
                'duration_minutes' not in data):
            raise serializers.ValidationError('open_until field or at least one of duration fields should be provided')

        if ('open_until' in data and
                ('duration_days' in data or 'duration_hours' in data or 'duration_minutes' in data)):
            raise serializers.ValidationError(
                'open_until field and duration fields should not be provided at the same time'
            )

        if 'open_until' in data and data['open_until'] <= timezone.now():
            raise serializers.ValidationError(
                'open_until field cannot be past or present datetime'
            )

        if ('open_until' not in data and
                ('duration_days' not in data or int(data['duration_days']) == 0) and
                ('duration_hours' not in data or int(data['duration_hours']) == 0) and
                ('duration_minutes' not in data or int(data['duration_minutes']) == 0)):
            raise serializers.ValidationError(
                'At least of one of duration fields should be larger than zero'
            )

        return data


class BidSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bid
        fields = ('pk', 'price', 'status', 'placed_at', 'closed_at', 'user', 'auction')
        read_only_fields = ('pk', 'status', 'placed_at', 'closed_at', 'user', 'auction')

    def validate_price(self, value):
        auction = self.context.get('view').get_object()
        if value <= auction.current_price:
            raise serializers.ValidationError('Price should be higher than current price of this auction')

        return value

    def validate(self, data):
        data = super(BidSerializer, self).validate(data)
        auction = self.context.get('view').get_object()

        if auction.status != AUCTION_STATUS_OPEN:
            raise serializers.ValidationError('Bids can be placed to open auctions only')

        if auction.open_until and auction.open_until < timezone.now():
            raise serializers.ValidationError('This auction is now waiting to close')

        return data

    @transaction.atomic
    def create(self, validated_data):
        request = self.context.get('request')
        user = request.user
        auction = self.context.get('view').get_object()
        price = validated_data['price']
        placed_at = timezone.now()

        try:
            bid = Bid.objects.get(user=user, auction=auction)
            bid.price = price
            bid.placed_at = placed_at
            bid.save()
        except Bid.DoesNotExist:
            bid = Bid.objects.create(
                price=price,
                placed_at=placed_at,
                user=user,
                auction=auction
            )
        except Bid.MultipleObjectsReturned:
            Bid.objects.filter(user=user).filter(auction=auction).delete()
            bid = Bid.objects.create(
                price=price,
                placed_at=placed_at,
                user=user,
                auction=auction
            )

        HistoryRecord.objects.create_history_record(user, auction, HISTORY_RECORD_USER_BID, {
            'price': price,
            'placed_at': placed_at,
        })

        bids = auction.bid_set.filter(status=BID_STATUS_ACTIVE).select_related('user')
        user_emails = []

        for bid in bids:
            if bid.user.pk != user.pk:
                Notification.objects.create_notification(bid.user, auction, NOTIFICATION_AUCTION_NEW_BID, {
                    'price': price,
                    'placed_at': placed_at,
                })
                user_emails.append(bid.user.email)

        send_email(
            'New bid has been placed',
            'A new bid has been placed on auction {}'.format(auction.title),
            user_emails
        )

        return bid


class BidDetailSerializer(serializers.ModelSerializer):
    user_detail = UserSerializer(source='user')
    auction_details = AuctionSerializer(source='auction')

    class Meta:
        model = Bid
        fields = ('pk', 'price', 'status', 'placed_at', 'closed_at', 'user', 'user_detail', 'auction', 'auction_details')
        read_only_fields = ('pk', 'price', 'status', 'placed_at', 'closed_at', 'user', 'user_detail', 'auction', 'auction_details')


class BidWithUserDetailSerializer(serializers.ModelSerializer):
    user_detail = serializers.SerializerMethodField()

    class Meta:
        model = Bid
        fields = ('pk', 'price', 'status', 'placed_at', 'closed_at', 'user', 'user_detail', 'auction')
        read_only_fields = ('pk', 'price', 'status', 'placed_at', 'closed_at', 'user', 'user_detail', 'auction')

    def get_user_detail(self, obj):
        return UserSerializer(obj.user).data


class BidStatusChangeSerializer(serializers.ModelSerializer):
    active = serializers.BooleanField(write_only=True)
    user_detail = serializers.SerializerMethodField()

    class Meta:
        model = Bid
        fields = ('pk', 'price', 'status', 'placed_at', 'closed_at', 'user', 'user_detail', 'auction', 'active')
        read_only_fields = ('pk', 'price', 'status', 'placed_at', 'closed_at', 'user', 'user_detail', 'auction')

    def get_user_detail(self, obj):
        return UserSerializer(obj.user).data

    def update(self, instance, validated_data):
        target_status = BID_STATUS_ACTIVE if validated_data['active'] else BID_STATUS_REJECTED

        if instance.status != BID_STATUS_ACTIVE and instance.status != BID_STATUS_REJECTED:
            raise ParseError('Invalid current status of this bid')

        if instance.status == target_status:
            raise ParseError('Invalid status change')

        instance.status = target_status
        instance.save()

        return instance


class SaleSerializer(serializers.ModelSerializer):
    winner = serializers.SerializerMethodField()
    charity = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = (
            'pk', 'winner', 'price', 'charity',
            'item_sent', 'tracking_number', 'cheque_sent_at', 'receipt_received_at',
            'status', 'note'
        )
        read_only_fields = ('pk', 'winner', 'price', 'charity', 'note')

    def get_winner(self, obj):
        return '{} {}'.format(obj.user.first_name, obj.user.last_name)

    def get_charity(self, obj):
        return obj.auction.charity.title


class SaleNoteSerializer(SaleSerializer):
    class Meta:
        model = Sale
        fields = SaleSerializer.Meta.fields
        read_only_fields = ('pk', 'winner', 'price', 'charity', 'item_sent', 'tracking_number', 'status')


class AuctionBacklogSerializer(serializers.ModelSerializer):
    highest_bid = BidWithUserDetailSerializer()
    product = ProductDetailSerializer()
    sale = SaleSerializer()

    class Meta:
        model = Auction
        fields = ('pk', 'title', 'status', 'highest_bid', 'product', 'sale')
        read_only_fields = ('pk', 'title', 'status', 'highest_bid', 'product', 'sale')
