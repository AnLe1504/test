from django.db import models


class Circuit(models.Model):
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=255)
    city = models.CharField(max_length=255, null=True, blank=True)
    lap_length_km = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    first_gp_year = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=20)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'circuits'

    def __str__(self):
        return self.name


class Trip(models.Model):
    trip_name = models.CharField(max_length=255)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'trips'

    def __str__(self):
        return self.trip_name


class CircuitVisit(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, db_column='trip_id')
    circuit = models.ForeignKey(Circuit, on_delete=models.CASCADE, db_column='circuit_id')
    race_year = models.IntegerField(null=True, blank=True)
    ticket_type = models.CharField(max_length=100, null=True, blank=True)
    seating_section = models.CharField(max_length=100, null=True, blank=True)
    personal_rating = models.IntegerField(null=True, blank=True)
    personal_notes = models.TextField(null=True, blank=True)
    attended = models.BooleanField(default=False)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'circuit_visits'


class BucketList(models.Model):
    circuit = models.ForeignKey(Circuit, on_delete=models.CASCADE, db_column='circuit_id')
    priority = models.CharField(max_length=20)
    added_notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'bucket_list'
