from django.urls import path
from .views import (
    home_view,
    trips_list, trip_edit, trip_delete, race_dates_api,
    circuit_list, circuit_detail_panel, bucket_add, visit_edit, visit_delete,
    visits_list, bucket_list, bucket_remove,
    circuit_manage, circuit_edit, circuit_delete,
)

urlpatterns = [
    path('', home_view, name='home'),
    path('trips/', trips_list, name='trips_list'),
    path('trips/<int:trip_id>/edit/', trip_edit, name='trip_edit'),
    path('trips/<int:trip_id>/delete/', trip_delete, name='trip_delete'),
    path('api/race-dates/', race_dates_api, name='race_dates_api'),
    path('circuits/', circuit_list, name='circuit_list'),
    path('circuits/<int:circuit_id>/panel/', circuit_detail_panel, name='circuit_panel'),
    path('bucket-list/add/', bucket_add, name='bucket_add'),
    path('visits/', visits_list, name='visits_list'),
    path('visits/<int:visit_id>/edit/', visit_edit, name='visit_edit'),
    path('visits/<int:visit_id>/delete/', visit_delete, name='visit_delete'),
    path('bucket-list/', bucket_list, name='bucket_list'),
    path('bucket-list/<int:bl_id>/remove/', bucket_remove, name='bucket_remove'),
    path('manage-circuits/', circuit_manage, name='circuit_manage'),
    path('manage-circuits/<int:circuit_id>/edit/', circuit_edit, name='circuit_edit'),
    path('manage-circuits/<int:circuit_id>/delete/', circuit_delete, name='circuit_delete'),
]
