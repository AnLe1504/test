from django.contrib import admin
from .models import Circuit, Trip, CircuitVisit, BucketList


@admin.register(Circuit)
class CircuitAdmin(admin.ModelAdmin):
    list_display = ('name', 'country', 'city', 'lap_length_km', 'first_gp_year', 'source')
    search_fields = ('name', 'country', 'city')
    list_filter = ('source', 'country')


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ('trip_name', 'start_date', 'end_date', 'status')
    list_filter = ('status',)
    search_fields = ('trip_name',)


@admin.register(CircuitVisit)
class CircuitVisitAdmin(admin.ModelAdmin):
    list_display = ('circuit', 'trip', 'race_year', 'attended', 'personal_rating')
    list_filter = ('attended', 'race_year')


@admin.register(BucketList)
class BucketListAdmin(admin.ModelAdmin):
    list_display = ('circuit', 'priority', 'created_at')
    list_filter = ('priority',)
